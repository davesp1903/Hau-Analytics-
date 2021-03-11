import os
import csv
import matplotlib
import matplotlib.pyplot as plt
import datetime
import pytz
import matplotlib.dates as mdates
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.animation import FuncAnimation
import numpy as np
import scipy.stats as si

import sqlite3
import concurrent.futures
import multiprocessing
from OpraFeed.securityclass import Security
from BlackSholesMerton.Black_Sholes_Merton import BlackSholesMerton, iv_from_price, risk_free_rate, dividends, calendar_days_from_expiration
from datetime import timedelta
from SABR_Hagan import SABR as SABR


matplotlib.use('TkAgg')


class Trade:

    def __init__(self, underlying, quote_datetime, sequence_number, root, expiration, strike, option_type, exchange_id,
                 trade_size, trade_price, trade_condition_id, canceled_trade_condition, best_bid, best_ask,
                 underlying_bid, underlying_ask, number_of_exchanges, exchange_sequence: list, trade_iv=None,
                 trade_delta=None):

        # Initialize row fields as attributes

        self.underlying = underlying
        self.quote_datetime = quote_datetime
        self.sequence_number = sequence_number
        self.root = root
        self.expiration = expiration
        self.strike = strike
        if option_type == 'C' or option_type == 'CALL':
            self.option_type = 'CALL'
        else:
            self.option_type = 'PUT'
        self.exchange_id = exchange_id
        self.trade_size = int(trade_size)
        self.trade_price = trade_price
        self.trade_condition_id = trade_condition_id
        self.canceled_trade_condition = canceled_trade_condition
        self.best_bid = best_bid
        self.best_ask = best_ask
        self.trade_iv = float(trade_iv) if trade_iv is not None else trade_iv
        self.trade_delta = trade_delta
        self.underlying_bid = underlying_bid
        self.underlying_ask = underlying_ask
        self.underlying_price = (float(self.underlying_bid) + float(self.underlying_ask)) / 2.0
        self.number_of_exchanges = number_of_exchanges

        op_type = 'STOCK'
        if dividends[self.underlying] != 0:
            op_type = 'DIVIDEND'

        # turn exchange list into dictionary with exchange id as key and liqudity stats/ba stats as values
        self.by_exchange = {}

        self._exchange_sequence = exchange_sequence

        for exchange in self.split_exchanges():
            ex_id, data = exchange[0], exchange[1::]
            data = [item.rstrip() for item in data]
            self.by_exchange[ex_id] = data

        # initialize inference to none
        self.inference = 'NONE'

        # underlying price is midpoint of bid/ask
        self.underlying_price = (float(self.underlying_ask) + float(self.underlying_bid)) / 2

        # strike as percentage deviation from underlying spot
        try:
            self.deviation_percent_rounded = round((float(self.strike) - self.underlying_price) / self.underlying_price * 100)
        except ZeroDivisionError:
            self.deviation_percent_rounded = 0.1

        # convert %Y-%M-%D expiration date into an integer representing the number of days into the future,
            # and express that as a fraction of trading days in 2020 (253)

        # print('PRICE = {}'.format(self.trade_price))

        # self.t = self.get_ttm(today=self.quote_datetime[:10], expiration=self.expiration)/253
        # print('Expiration = {} ({})'.format(self.expiration, self.t))

        # use recursive function to iterate volatility



        # T = calendar_days_from_expiration(today=self.quote_datetime[0:10], expiration=self.expiration) / 365
        self.T = self.get_T()

        # use file iv if calcs is true, otherwise will use binary search to solve from price

        self.volatility = self.trade_iv
        if self.volatility is None:
            self.volatility = iv_from_price(option_price=float(self.trade_price), S=float(self.underlying_price),
                                            K=float(self.strike), T=self.T, option_type=self.option_type,
                                            q=dividends[self.underlying])

        # black sholes model

        model = BlackSholesMerton(S=self.underlying_price, K=float(self.strike), r=risk_free_rate,
                                  q=dividends[self.underlying],
                                  T=self.T,
                                  option_type=self.option_type, cost_of_carry_type=op_type,
                                  sigma=self.volatility)

        # delta

        if self.trade_delta is None:
            self.trade_delta = model.Delta

        self.delta = round(model.Delta * float(trade_size) * 100.0, 5)
        self.gamma = round(model.Gamma * float(trade_size) * 100.0, 5)
        self.vega = round(model.Vega * float(trade_size) * 100.0, 5)
        self.vanna = round(model.DdelV * float(trade_size) * 100.0, 5)

    def set_inference(self, inference: str) -> None:
        self.inference = inference

    def split_exchanges(self):
        counter = 0
        exchanges = []
        last = 0
        for element in self._exchange_sequence:
            counter += 1
            # print(element, '---->', self._exchange_sequence.index(element))

            if counter % 5 == 0:
                exchanges.append(self._exchange_sequence[(last):counter])
                last = counter

        return exchanges

    def __str__(self):
        print('=' * 75)
        print("TRADE: {} // @ {}".format(self.sequence_number, self.quote_datetime))
        print("{} of the {} {} {}s @ {}".format(self.trade_size, self.underlying, self.expiration,
                                                self.option_type, self.strike))
        print('B/A: {}/{}-----> filled @ {}'.format(self.best_bid, self.best_ask, self.trade_price))
        print('/' * 30)
        print("BY EXCHANGE:")
        for exchange in self.by_exchange:
            print("Exchange ID {}--->".format(exchange))
            data = self.by_exchange[exchange]
            print(" \t || Bid Size: {:4} || Bid: {:4} || Ask Size: {:4} || Ask: {:4}".format(data[0], data[1], data[2], data[3]))
        print('=' * 75)
        return ''

    def get_T(self):
        date = self.quote_datetime

        now = datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
        future = datetime.datetime.strptime('{} 16:00:00.000'.format(self.expiration), '%Y-%m-%d %H:%M:%S.%f')

        diff = future - now

        T = diff.total_seconds() / (365 * 24 * 60 * 60)
        return T

        # print('T = {}'.format(diff.total_seconds() / (365 * 23 * 60 * 60)))

class Strike:

    def __init__(self, strike_price: str) -> None:
        self.strike_price = strike_price
        self.buys, self.sells, self.uninferred = [], [], []

        self.calls, self.puts = [], []

        self.number_of_calls, self.number_of_puts = len(self.calls), len(self.puts)

        self.total = (len(self.buys) + len(self.sells) + len(self.uninferred))

        self.callDDOI = 0
        self.putDDOI = 0

    def add_trade(self, trade: Trade):

        if trade.inference == 'BUY':
            self.buys.append(trade)
        elif trade.inference == 'SELL':
            self.sells.append(trade)
        elif trade.inference == 'NONE':
            self.uninferred.append(trade)
        if trade.option_type == 'CALL':

            self.calls.append(trade)
            self.add_to_call_length(trade.trade_size)

        elif trade.option_type == 'PUT':

            self.puts.append(trade)
            self.add_to_put_length(trade.trade_size)

        self.add_to_total(1)

        # adjust DDOI

        if trade.option_type == 'CALL':
            if trade.inference == 'BUY':
                if trade.strike == '23.000' and trade.expiration == '2020-04-24':
                    print('THIS IS A BUY of {} size'.format(trade.trade_size))
                    print('DDOI was {}'.format(self.callDDOI))

                self.callDDOI -= trade.trade_size
                if trade.strike == '23.000' and trade.expiration == '2020-04-24':
                    print('DDDOI is NOW {}'.format(self.callDDOI))
            elif trade.inference == 'SELL':
                if trade.strike == '23.000' and trade.expiration == '2020-04-24':
                    print('THIS IS A SELL of {} size'.format(trade.trade_size))
                    print('DDOI was {}'.format(self.callDDOI))
                self.callDDOI += trade.trade_size
                if trade.strike == '23.000' and trade.expiration == '2020-04-24':
                    print('DDDOI is NOW {}'.format(self.callDDOI))

        elif trade.option_type == 'PUT':

            if trade.inference == 'BUY':
                self.putDDOI -= trade.trade_size
            elif trade.inference == 'SELL':
                self.putDDOI += trade.trade_size

    def set_statistical_measures(self) -> None:
        calls_bought, calls_sold = 0, 0
        puts_bought, puts_sold = 0, 0

        for trade in self.calls:
            if trade in self.buys:
                calls_bought += trade.trade_size
            elif trade in self.sells:
                calls_sold += trade.trade_size

        for trade in self.puts:
            if trade in self.buys:
                puts_bought += trade.trade_size
            elif trade in self.sells:
                puts_sold += trade.trade_size

        self.__setattr__('calls_bought', calls_bought)
        self.__setattr__('calls_sold', calls_sold)
        self.__setattr__('puts_bought', puts_bought)
        self.__setattr__('puts_sold', puts_sold)

    def add_to_total(self, value):
        self.total += value

    def add_to_call_length(self, value):
        self.number_of_calls += value

    def add_to_put_length(self, value):
        self.number_of_puts += value


class Aggregator:

    def __init__(self):

        self.summation_strikes = {}
        self.expirations = {}
        self.total_trades = 0

    def accept_payload(self, payload: tuple) -> None:
        feed_summation_strikes, feed_expirations = payload

        for exp in feed_expirations:
            if exp not in self.expirations.keys():
                self.initialize_expiration_dictionary(exp)
            for strike in feed_expirations[exp].strikes:
                if strike.strike_price not in self.expirations[exp].keys():
                    self.initliaze_entry_expirations(exp, strike)
                else:
                    self.add_entry_expirations(exp, strike)

        for strike in feed_summation_strikes:
            if strike.strike_price not in self.summation_strikes:
                self.initialize_summation_strike_entry(strike=strike)
            else:
                self.add_summation_strike_entry(strike=strike)

    def initialize_summation_strike_entry(self, strike: Strike) -> None:
        strike.set_statistical_measures()
        self.summation_strikes[strike.strike_price] = {'Calls': {'number_bought': strike.calls_bought, 'number_sold': strike.calls_sold, 'total': strike.number_of_calls},
                                                       'Puts': {'number_bought': strike.puts_bought, 'number_sold': strike.puts_sold, 'total': strike.number_of_puts}}
        self.total_trades += strike.number_of_calls
        self.total_trades += strike.number_of_puts

    def add_summation_strike_entry(self, strike: Strike):
        strike.set_statistical_measures()
        self.summation_strikes[strike.strike_price]['Calls']['number_bought'] += strike.calls_bought
        self.summation_strikes[strike.strike_price]['Calls']['number_sold'] += strike.calls_sold
        self.summation_strikes[strike.strike_price]['Calls']['total'] += strike.number_of_calls
        self.summation_strikes[strike.strike_price]['Puts']['number_bought'] += strike.puts_bought
        self.summation_strikes[strike.strike_price]['Puts']['number_sold'] += strike.puts_sold
        self.summation_strikes[strike.strike_price]['Puts']['total'] += strike.number_of_puts

        self.total_trades += strike.number_of_calls
        self.total_trades += strike.number_of_puts

    def initialize_expiration_dictionary(self, date: str) -> None:
        self.expirations[date] = {}

    def initliaze_entry_expirations(self, date: str, strike: Strike):
        strike.set_statistical_measures()
        self.expirations[date][strike.strike_price] = {'Calls': {'number_bought': strike.calls_bought, 'number_sold': strike.calls_sold, 'total': strike.number_of_calls},
                                                      'Puts': {'number_bought': strike.puts_bought, 'number_sold': strike.puts_sold, 'total': strike.number_of_puts}}

    def add_entry_expirations(self, date: str, strike: Strike) -> None:
        strike.set_statistical_measures()
        proper_expiry = self.expirations[date]
        proper_expiry[strike.strike_price]['Calls']['number_bought'] += strike.calls_bought
        proper_expiry[strike.strike_price]['Calls']['number_sold'] += strike.calls_sold
        proper_expiry[strike.strike_price]['Calls']['total'] += strike.number_of_calls
        proper_expiry[strike.strike_price]['Puts']['number_bought'] += strike.puts_bought
        proper_expiry[strike.strike_price]['Puts']['number_sold'] += strike.puts_sold
        proper_expiry[strike.strike_price]['Puts']['total'] += strike.number_of_puts


    def __str__(self):
        print('SUMMATION STATISTICS --- {} total trades'.format(self.total_trades))

        print('\t\t  CALL','\t\t\t\t  STRIKE', '\t\t\t\t  PUT')
        for strike in sorted(self.summation_strikes):
            dictionary = self.summation_strikes[strike]
            try:
                percent_calls_bought = round((dictionary['Calls']['number_bought'] / dictionary['Calls']['total']) * 100, 2)
            except ZeroDivisionError:
                percent_calls_bought = 0
            try:
                percent_calls_sold = round((dictionary['Calls']['number_sold'] / dictionary['Calls']['total']) * 100, 2)
            except ZeroDivisionError:
                percent_calls_sold = 0
            try:
                percent_puts_bought = round((dictionary['Puts']['number_bought'] / dictionary['Puts']['total']) * 100, 2)
            except ZeroDivisionError:
                percent_puts_bought = 0
            try:
                percent_puts_sold = round((dictionary['Puts']['number_sold'] / dictionary['Puts']['total']) * 100, 2)
            except ZeroDivisionError:
                percent_puts_sold = 0

            total = dictionary['Calls']['total'] + dictionary['Puts']['total']

            print('{:5}% Buy {:5}% Sell'.format(percent_calls_bought, percent_calls_sold), '<-----',
                  strike, '-----> {:5}% Buy {:5}% Sell'.format(percent_puts_bought, percent_puts_sold), '|', '{:5} Total ({}/{})'.format(total, dictionary['Calls']['total'], dictionary['Puts']['total']))
        for exp in sorted(self.expirations):
            strike_keys = self.expirations[exp]

            print('=' * 100)
            print(exp)
            print('\t\t  CALL','\t\t\t\t  STRIKE', '\t\t\t\t  PUT')
            for strike_key in sorted(strike_keys):
                dictionary = self.expirations[exp][strike_key]
                try:
                    percent_calls_bought = round((dictionary['Calls']['number_bought'] / dictionary['Calls']['total']) * 100, 2)
                except ZeroDivisionError:
                    percent_calls_bought = 0.0
                try:
                    percent_calls_sold = round((dictionary['Calls']['number_sold'] / dictionary['Calls']['total']) * 100, 2)
                except ZeroDivisionError:
                    percent_calls_sold = 0.0
                try:
                    percent_puts_bought = round((dictionary['Puts']['number_bought'] / dictionary['Puts']['total']) * 100, 2)
                except ZeroDivisionError:
                    percent_puts_bought = 0.0
                try:
                    percent_puts_sold = round((dictionary['Puts']['number_sold'] / dictionary['Puts']['total']) * 100, 2)
                except ZeroDivisionError:
                    percent_puts_sold = 0.0
                total = dictionary['Calls']['total'] + dictionary['Puts']['total']

                print('{:5}% Buy {:5}% Sell'.format(percent_calls_bought, percent_calls_sold), '<-----',
                      strike_key, '-----> {:5}% Buy {:5}% Sell'.format(percent_puts_bought, percent_puts_sold), '|', '{:5} Total ({}/{})'.format(total, dictionary['Calls']['total'], dictionary['Puts']['total']))
        return ''

    def to_csv(self, attribute, description: str) -> None:
        if attribute == self.summation_strikes:
            with open('Summation Statistics for {}.csv'.format(description), 'w') as file:
                writer = csv.writer(file)
                writer.writerow(['Percent_Calls_Bought', 'Percent_Calls_Sold', 'Strike', 'Percent_Puts_Bought', 'Percent_Puts_Sold', 'Totals'])
                for strike in sorted(self.summation_strikes):
                    dictionary = self.summation_strikes[strike]
                    try:
                        percent_calls_bought = round((dictionary['Calls']['number_bought'] / dictionary['Calls']['total']) * 100, 2)
                    except ZeroDivisionError:
                        percent_calls_bought = 0
                    try:
                        percent_calls_sold = round((dictionary['Calls']['number_sold'] / dictionary['Calls']['total']) * 100, 2)
                    except ZeroDivisionError:
                        percent_calls_sold = 0
                    try:
                        percent_puts_bought = round((dictionary['Puts']['number_bought'] / dictionary['Puts']['total']) * 100, 2)
                    except ZeroDivisionError:
                        percent_puts_bought = 0
                    try:
                        percent_puts_sold = round((dictionary['Puts']['number_sold'] / dictionary['Puts']['total']) * 100, 2)
                    except ZeroDivisionError:
                        percent_puts_sold = 0

                    total = dictionary['Calls']['total'] + dictionary['Puts']['total']
                    writer.writerow(['{:5}%'.format(percent_calls_bought), '{:5}%'.format(percent_calls_sold),
                          strike, '{:5}%'.format(percent_puts_bought), '{:5}%'.format(percent_puts_sold), '{:5} Total ({}/{})'.format(total, dictionary['Calls']['total'], dictionary['Puts']['total'])])

    def to_txt(self, file_name: str) -> None:
        with open(file_name, 'w') as file:
            print('SUMMATION STATISTICS --- {} total trades'.format(self.total_trades), file=file)
            print('\t\t  CALL','\t\t\t\t  STRIKE', '\t\t\t\t  PUT', file=file)
            for strike in sorted(self.summation_strikes):
                dictionary = self.summation_strikes[strike]
                try:
                    percent_calls_bought = round((dictionary['Calls']['number_bought'] / dictionary['Calls']['total']) * 100, 2)
                except ZeroDivisionError:
                    percent_calls_bought = 0
                try:
                    percent_calls_sold = round((dictionary['Calls']['number_sold'] / dictionary['Calls']['total']) * 100, 2)
                except ZeroDivisionError:
                    percent_calls_sold = 0
                try:
                    percent_puts_bought = round((dictionary['Puts']['number_bought'] / dictionary['Puts']['total']) * 100, 2)
                except ZeroDivisionError:
                    percent_puts_bought = 0
                try:
                    percent_puts_sold = round((dictionary['Puts']['number_sold'] / dictionary['Puts']['total']) * 100, 2)
                except ZeroDivisionError:
                    percent_puts_sold = 0

                total = dictionary['Calls']['total'] + dictionary['Puts']['total']

                print('{:5}% Buy {:5}% Sell'.format(percent_calls_bought, percent_calls_sold), '<-----',
                      strike, '-----> {:5}% Buy {:5}% Sell'.format(percent_puts_bought, percent_puts_sold), '|',
                      '{:5} Total ({}/{})'.format(total, dictionary['Calls']['total'], dictionary['Puts']['total']),
                      file=file)

            for exp in sorted(self.expirations):
                strike_keys = self.expirations[exp]
                print('=' * 100, file=file)
                print(exp, file=file)
                print('\t\t  CALL','\t\t\t\t  STRIKE', '\t\t\t\t  PUT', file=file)
                for strike_key in sorted(strike_keys):
                    dictionary = self.expirations[exp][strike_key]
                    try:
                        percent_calls_bought = round((dictionary['Calls']['number_bought'] / dictionary['Calls']['total']) * 100, 2)
                    except ZeroDivisionError:
                        percent_calls_bought = 0.0
                    try:
                        percent_calls_sold = round((dictionary['Calls']['number_sold'] / dictionary['Calls']['total']) * 100, 2)
                    except ZeroDivisionError:
                        percent_calls_sold = 0.0
                    try:
                        percent_puts_bought = round((dictionary['Puts']['number_bought'] / dictionary['Puts']['total']) * 100, 2)
                    except ZeroDivisionError:
                        percent_puts_bought = 0.0
                    try:
                        percent_puts_sold = round((dictionary['Puts']['number_sold'] / dictionary['Puts']['total']) * 100, 2)
                    except ZeroDivisionError:
                        percent_puts_sold = 0.0
                    total = dictionary['Calls']['total'] + dictionary['Puts']['total']

                    print('{:5}% Buy {:5}% Sell'.format(percent_calls_bought, percent_calls_sold), '<-----',
                          strike_key, '-----> {:5}% Buy {:5}% Sell'.format(percent_puts_bought, percent_puts_sold), '|', '{:5} Total ({}/{})'.format(total, dictionary['Calls']['total'], dictionary['Puts']['total']), file=file)


class Expiration:

    def __init__(self, date):
        self.expiration_date = date
        self.strikes = []

    def add_strike(self, strike: Strike):
        self.strikes.append(strike)

    def set_statistical_measures(self):
        bought_sum, sold_sum, uninferred_sum = 0, 0, 0
        for strike in self.strikes:

            for trade in strike.buys:
                bought_sum += 1
            for trade in strike.sells:
                sold_sum += 1
            for trade in strike.uninferred:
                uninferred_sum += 1

        total = bought_sum + sold_sum + uninferred_sum
        # print('total = {}'.format(total))
        # print('percents = {}, {}'.format(bought_sum, sold_sum))
        percent_bought = round((bought_sum / total) * 100, 2)
        percent_sold = round((sold_sum / total) * 100, 2)

        self.__setattr__('percent_bought', percent_bought)
        self.__setattr__('percent_sold', percent_sold)


class OpraFeed:

    def __init__(self, folder: str, flagger_function, binning_method='strike', calcs=True, curves=True):

        self.calcs = calcs
        self.curves = curves

        self.ATM_calls_bought, self.ATM_calls_sold, self.ATM_calls_total = 0, 0, 0
        self.OTM_calls_bought, self.OTM_calls_sold, self.OTM_calls_total = 0, 0, 0
        self.ITM_calls_bought, self.ITM_calls_sold, self.ITM_calls_total = 0, 0, 0

        self.ATM_puts_bought, self.ATM_puts_sold, self.ATM_puts_total = 0, 0, 0
        self.OTM_puts_bought, self.OTM_puts_sold, self.OTM_puts_total = 0, 0, 0
        self.ITM_puts_bought, self.ITM_puts_sold, self.ITM_puts_total = 0, 0, 0

        self.notional_vega = 0


        self.binner = binning_method
        self.flagger = flagger_function
        self.file_paths = sorted(os.listdir(folder))
        self.aggregator = Aggregator()
        self.liquidity_tracker = Liquidity()
        self.strikegamma = StrikeGamma()

        os.chdir(folder)
        working_directory = os.getcwd()
        file_path_names = []
        for item in self.file_paths:
            if item != '.DS_Store':
                new_file_path = working_directory + '/{}'.format(item)
                file_path_names.append(new_file_path)

        for f in file_path_names:
            self.trades = []
            self.expirations = {}

            self.summation_strikes = []

            self.calls, self.puts = [], []
            self.number_of_calls, self.number_of_puts = 0, 0
            with open(f) as file:
                data = file.readlines()
                data = data[1::]
                eighth = len(data) // 8
                data1 = data[0:eighth]
                data2 = data[eighth:eighth*2]
                data3 = data[eighth*2:eighth*3]
                data4 = data[eighth*3:eighth*4]
                data5 = data[eighth*4:eighth*5]
                data6 = data[eighth*5:eighth*6]
                data7 = data[eighth*6:eighth*7]
                data8 = data[eighth*7:eighth*8]

                data_list = [data1, data2, data3, data4, data5, data6, data7, data8 ]
                # self.bar = IncrementalBar('{} progress'.format(data), max=len(data))

                with concurrent.futures.ProcessPoolExecutor() as ex:
                    g = ex.map(self.process_data, data_list)

                    for trades_list in g:
                        self.trades.extend(trades_list)
                # for line in data:
                #
                #     split_line = line.split(',')
                #     # print(split_line)
                #     trade = Trade(underlying=split_line[0], quote_datetime=split_line[1], sequence_number=split_line[2],
                #                   root=split_line[3], expiration=split_line[4], strike=split_line[5], option_type=split_line[6],
                #                   exchange_id=split_line[7], trade_size=split_line[8], trade_price=split_line[9],
                #                   trade_condition_id=split_line[10], canceled_trade_condition=split_line[11],
                #                   best_bid=split_line[12], best_ask=split_line[13], underlying_bid=split_line[14],
                #                   underlying_ask=split_line[15], number_of_exchanges=split_line[16],
                #                   exchange_sequence=split_line[17::])
                #     self.trades.append(trade)
                #     print(trade.trade_price, trade.option_type)
                #     bar.next()
            # self.bar.finish()
            print('finished with {}'.format(f))

            # 2021 Addition - Vol Curve Objects

            if self.curves is True:
                self.TimeStamps = TimeStampArchive(trades=self.trades)
                self.CurveArchive = CurveArchive(archive=self.TimeStamps)

            self.liquidity_tracker.accept_new_trades(self.trades)
            self.buys, self.sells, self.uninferred = self.classify()
            self.set_statistical_measures()
            self.to_aggregator(aggregator=self.aggregator)
            self.strikegamma.accept_strike_gamma(self.trades)



        self.underlying_symbol = self.trades[3].underlying
        if self.underlying_symbol in ['$SPX.X', '^SPX']:
            self.underlying_symbol = '$SPX.X'

        try:
            self.percent_ATM_calls_bought = self.ATM_calls_bought / self.ATM_calls_total * 100
        except ZeroDivisionError:
            self.percent_ATM_calls_bought = 0

        try:
            self.percent_ATM_calls_sold = self.ATM_calls_sold / self.ATM_calls_total * 100
        except ZeroDivisionError:
            self.percent_ATM_calls_sold = 0

        try:
            self.percent_OTM_calls_bought = self.OTM_calls_bought / self.OTM_calls_total * 100
        except ZeroDivisionError:
            self.percent_OTM_calls_bought = 0

        try:
            self.percent_OTM_calls_sold = self.OTM_calls_sold / self.OTM_calls_total * 100
        except ZeroDivisionError:
            self.percent_OTM_calls_sold = 0

        try:
            self.percent_ITM_calls_bought = self.ITM_calls_bought / self.ITM_calls_total * 100
        except ZeroDivisionError:
            self.percent_ITM_calls_bought = 0

        try:
            self.percent_ITM_calls_sold = self.ITM_calls_sold / self.ITM_calls_total * 100
        except ZeroDivisionError:
            self.ppercent_ITM_calls_sold = 0

        try:
            self.percent_ATM_puts_bought = self.ATM_puts_bought / self.ATM_puts_total * 100
        except ZeroDivisionError:
            self.percent_ATM_puts_bought = 0

        try:
            self.percent_ATM_puts_sold = self.ATM_puts_sold / self.ATM_puts_total * 100
        except ZeroDivisionError:
            self.percent_ATM_puts_sold = 0

        try:
            self.percent_OTM_puts_bought = self.OTM_puts_bought / self.OTM_puts_total * 100
        except ZeroDivisionError:
            self.percent_OTM_puts_bought = 0

        try:
            self.percent_OTM_puts_sold = self.OTM_puts_sold / self.OTM_puts_total * 100
        except ZeroDivisionError:
            self.percent_OTM_puts_sold = 0

        try:
            self.percent_ITM_puts_bought = self.ITM_puts_bought / self.ITM_puts_total * 100
        except ZeroDivisionError:
            self.percent_ITM_puts_bought = 0
        try:
            self.percent_ITM_puts_sold = self.ITM_puts_sold / self.ITM_puts_total * 100
        except ZeroDivisionError:
            self.percent_ITM_puts_sold = 0

    def process_data(self, data):
        trades = []

        for line in data:

            split_line = line.split(',')

            try:
                if self.calcs is True:
                    trade = Trade(underlying=split_line[0], quote_datetime=split_line[1], sequence_number=split_line[2],
                                  root=split_line[3], expiration=split_line[4], strike=split_line[5], option_type=split_line[6],
                                  exchange_id=split_line[7], trade_size=split_line[8], trade_price=split_line[9],
                                  trade_condition_id=split_line[10], canceled_trade_condition=split_line[11],
                                  best_bid=split_line[12], best_ask=split_line[13], trade_iv=split_line[14], trade_delta=split_line[15], underlying_bid=split_line[16],
                                  underlying_ask=split_line[17], number_of_exchanges=split_line[18],
                                  exchange_sequence=split_line[19::])
                else:
                    trade = Trade(underlying=split_line[0], quote_datetime=split_line[1], sequence_number=split_line[2],
                                    root=split_line[3], expiration=split_line[4], strike=split_line[5], option_type=split_line[6],
                                    exchange_id=split_line[7], trade_size=split_line[8], trade_price=split_line[9],
                                    trade_condition_id=split_line[10], canceled_trade_condition=split_line[11],
                                    best_bid=split_line[12], best_ask=split_line[13], underlying_bid=split_line[14],
                                    underlying_ask=split_line[15], number_of_exchanges=split_line[16],
                                    exchange_sequence=split_line[17::])
                trades.append(trade)
                print(trade.trade_price, trade.option_type)
            except IndexError:
                continue
        return trades

    def get_timestamps(self):
        return self.TimeStamps

    def get_curve_archive(self):
        return self.CurveArchive

    def classify(self) -> tuple:
        buys, sells, uninferred = [], [], []
        self.instantiate_expirations()
        self.instantiate_strikes()
        self.instantiate_summation_strikes()

        for trade in self.trades:

            if self.binner == 'strike':
                element_bin = trade.strike
            else:
                element_bin = trade.deviation_percent_rounded

            try:
                test, inference = self.flagger(trade)
            except TypeError:
                test, inference = self.flagger(trade, self)

            # adjust liquidity tracker inference---------
            trades = self.liquidity_tracker.expirations[trade.expiration].strikes[trade.strike].time_stamps[trade.quote_datetime][trade.option_type]['trade_sizes']
            for test_tr in trades:
                if test_tr[1] == trade.sequence_number:
                    trades[trades.index(test_tr)] = (test_tr[0], test_tr[1], trade.inference, -test_tr[3] if trade.inference == 'SELL' else test_tr[3])
            # ---------------------------------------

            # DJUST ATM/OTM/ITM numbers ------------------------------
            test = self.atm_test(trade=trade)
            if test == 'ATM':
                if trade.inference == 'BUY':
                    if trade.option_type == 'CALL':
                        self.ATM_calls_bought += 1
                        self.ATM_calls_total += 1
                    else:
                        self.ATM_puts_bought += 1
                        self.ATM_puts_total += 1
                elif trade.inference == "SELL":
                    if trade.option_type == 'CALL':
                        self.ATM_calls_sold += 1
                        self.ATM_calls_total += 1
                    else:
                        self.ATM_puts_sold += 1
                        self.ATM_puts_total += 1

                else:
                    if trade.option_type == 'CALL':
                        self.ATM_calls_total += 1
                    else:
                        self.ATM_puts_total += 1

            elif test == 'ITM':
                if trade.inference == 'BUY':
                    if trade.option_type == 'CALL':
                        self.ITM_calls_bought += 1
                        self.ITM_calls_total += 1
                    else:
                        self.ITM_puts_bought += 1
                        self.ITM_puts_total += 1
                elif trade.inference == "SELL":
                    if trade.option_type == 'CALL':
                        self.ITM_calls_sold += 1
                        self.ITM_calls_total += 1
                    else:
                        self.ITM_puts_sold += 1
                        self.ITM_puts_total += 1

                else:
                    if trade.option_type == 'CALL':
                        self.ITM_calls_total += 1
                    else:
                        self.ITM_puts_total += 1
            elif test == 'OTM':
                if trade.inference == 'BUY':
                    if trade.option_type == 'CALL':
                        self.OTM_calls_bought += 1
                        self.OTM_calls_total += 1
                    else:
                        self.OTM_puts_bought += 1
                        self.OTM_puts_total += 1
                elif trade.inference == "SELL":
                    if trade.option_type == 'CALL':
                        self.OTM_calls_sold += 1
                        self.OTM_calls_total += 1
                    else:
                        self.OTM_puts_sold += 1
                        self.OTM_puts_total += 1

                else:
                    if trade.option_type == 'CALL':
                        self.OTM_calls_total += 1
                    else:
                        self.OTM_puts_total += 1
            # -------------------------------------------------------------

            # ADJUST VEGA NOTIONAL------------------------------------------
            if str(trade.vega) != 'nan':
                # print('vega was {}'.format(self.notional_vega))
                if trade.inference == 'BUY':
                    # print(trade.trade_size)
                    # print(trade.underlying_price)
                    # print(trade.vega)
                    self.notional_vega += (trade.vega * trade.underlying_price )
                elif trade.inference == "SELL":
                    # print(trade.trade_size)
                    # print(trade.underlying_price)
                    # print(trade.vega)
                    self.notional_vega -= (trade.vega * trade.underlying_price )
                # print('vega is now {}'.format(self.notional_vega))
            # ----------------------------------------------------------

            for exp in sorted(self.expirations):
                if trade.expiration == exp:
                    obj = self.expirations[exp]
                    for strike in obj.strikes:
                        if strike.strike_price == element_bin:
                            strike.add_trade(trade)

            if test is True:
                if inference == 'BUY':
                    buys.append(trade)
                elif inference == 'SELL':
                    sells.append(trade)
            else:
                uninferred.append(trade)

            if trade.option_type == 'CALL':
                self.calls.append(trade)
                self.add_to_call_length(1)
            elif trade.option_type == 'PUT':
                self.puts.append(trade)
                self.add_to_put_lenth(1)

            for strike in self.summation_strikes:
                if strike.strike_price == element_bin:
                    strike.add_trade(trade)

        return buys, sells, uninferred

    def add_to_call_length(self, value):
        self.number_of_calls += value

    def add_to_put_lenth(self, value):
        self.number_of_puts += value

    def instantiate_expirations(self) -> None:
        used = []
        for trade in self.trades:
            if trade.expiration not in used:
                used.append(trade.expiration)
                self.expirations[trade.expiration] = Expiration(trade.expiration)

    def instantiate_strikes(self) -> None:
        used = []
        for trade in self.trades:
            if self.binner == 'strike':
                element_bin = trade.strike
            else:
                element_bin = trade.deviation_percent_rounded

            if (trade.expiration, element_bin) not in used:
                used.append((trade.expiration, element_bin))
                proper_expiry = self.expirations[trade.expiration]
                proper_expiry.add_strike(Strike(element_bin))

    def instantiate_summation_strikes(self) -> None:
        used = []
        for trade in self.trades:
            if self.binner == 'strike':
                element_bin = trade.strike
            else:
                element_bin = trade.deviation_percent_rounded

            if element_bin not in used:
                used.append(element_bin)
                self.summation_strikes.append(Strike(element_bin))

    def set_statistical_measures(self) -> None:

        calls_bought, calls_sold = [], []
        puts_bought, puts_sold = [], []

        for trade in self.calls:
            if trade in self.buys:
                calls_bought.append(trade)
            elif trade in self.sells:
                calls_sold.append(trade)

        for trade in self.puts:
            if trade in self.buys:
                puts_bought.append(trade)
            elif trade in self.sells:
                puts_sold.append(trade)

        self.__setattr__('percent_calls_bought', round((len(calls_bought) / self.number_of_calls) * 100, 2))
        self.__setattr__('percent_calls_sold', round((len(calls_sold) / self.number_of_calls) * 100, 2))
        self.__setattr__('percent_puts_bought', round((len(puts_bought) / self.number_of_puts) * 100, 2))
        self.__setattr__('percent_puts_sold', round((len(puts_sold) / self.number_of_puts) * 100, 2))

    def atm_test(self, trade):

        ATM_strike = None
        dist = 1000000
        for strike in self.summation_strikes:
            distance = abs(float(strike.strike_price) - float(trade.underlying_price))
            if distance < dist:
                dist = distance
                ATM_strike = float(strike.strike_price)
        if float(trade.strike) == ATM_strike:
            return 'ATM'
        elif float(trade.strike) > ATM_strike:
            if trade.option_type == 'CALL':
                return 'OTM'
            else:
                return 'ITM'
        else:
            if trade.option_type == 'CALL':
                return 'ITM'
            else:
                return 'OTM'

    def delete_expired(self, cursor_con, date_compiled):
        sql = 'DELETE FROM DDOI WHERE expiration <= ? and isCurrent = 1'
        cursor_con.execute(sql, (date_compiled,))

    def to_database(self, database, security: Security, date_compiled='today'):
        tz = pytz.timezone('US/Eastern')
        today = datetime.datetime.now(tz=tz).strftime('%Y-%m-%d')

        if date_compiled == 'today':
            date_compiled = today
        else:
            date_compiled = date_compiled

        db = sqlite3.connect(database=database)
        cursor = db.cursor()
        insert_trade_sql = """INSERT INTO Trades VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        insert_exchange_sql = """INSERT INTO Exchanges VALUES((SELECT max(rowid) FROM Trades), ?, ?, ?, ?, ?)"""


        for trade in self.trades:
            cursor.execute(insert_trade_sql, (trade.underlying, trade.quote_datetime, trade.sequence_number, trade.root,
                                          trade.expiration, trade.strike, trade.option_type, trade.exchange_id,
                                          trade.trade_size, trade.trade_price, trade.trade_condition_id, trade.canceled_trade_condition,
                                          trade.best_bid, trade.best_ask, trade.underlying_bid, trade.underlying_ask,
                                          trade.number_of_exchanges, trade.volatility, trade.delta, trade.gamma,
                                          trade.vega, trade.vanna))
            for exchange in trade.by_exchange:
                data = trade.by_exchange[exchange]
                cursor.execute(insert_exchange_sql, (exchange, data[0], data[1], data[2], data[3]))

        # CREATES A COPY OF LAST UPDATE AND STORES IT WITH isCURRENT = 0
        print('CREATING COPY')
        copy_ddoi_sql = 'SELECT * FROM DDOI WHERE underlying_symbol = ? and isCurrent = 1'
        cursor.execute(copy_ddoi_sql, (self.underlying_symbol,))
        memory = [list(item) for item in cursor]
        adjusted = []
        for item in memory:
            print('memory item ')
            print(item)

            item[-1] = 0
            adjusted.append(tuple(item))
            print('adjusted item')
            print(item)

        re_insert_sql = "INSERT INTO DDOI VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        for tup in adjusted:
            try:
                cursor.execute(re_insert_sql, tup)
            except sqlite3.IntegrityError:
                print(tup)
                print('ERROR!')
        print('just completed ddoi map function !!!!')

        # cursor.execute('SELECT * FROM DDOI')
        # for item in cursor:
        #     print(item)
        # print('THAT WAS DDOI AFTER MOVING TABLE')


        # UPDATE LIVE DDOI TABLE WHERE isCurrent = 1
        update_live_sql = """UPDATE DDOI SET dealer_directional_open_interest
         = dealer_directional_open_interest + ?, quote_datetime = ?, premium = ?, implied_volatility = ?, delta = ?, gamma = ?, vega = ?, vanna = ?, open_interest = ?
          WHERE expiration = ? and strike = ? and option_type = ? and underlying_symbol = ? and isCurrent = 1"""
        exeption_update_live_sql = """UPDATE DDOI SET dealer_directional_open_interest
         = ?, quote_datetime = ?, premium = ?, implied_volatility = ?, delta = ?, gamma = ?, vega = ?, vanna = ?, open_interest = ?
          WHERE expiration = ? and strike = ? and option_type = ? and underlying_symbol = ? and isCurrent = 1"""
        inception_sql = """INSERT INTO DDOI VALUES ( ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

        test_Sql = 'SELECT quote_datetime FROM DDOI WHERE underlying_symbol = ? and isCurrent = 1'
        test = cursor.execute(test_Sql, (self.underlying_symbol, )).fetchall()
        if len(test) == 0:
            inception = True
        else:
            inception = False

        # self.delete_expired(cursor_con=cursor, date_compiled=date_compiled)
        print('STARTING DDOI ENTRIES.......' + '-' * 200)
        for expiration in security.expirations:
            print(expiration)
            if expiration >= date_compiled:
                for attr in security.expirations[expiration].calls, security.expirations[expiration].puts:

                    print('STARTING NEW ATTRIBUTE' + '-' * 100)
                    for strike in attr.keys():
                        strike_inception = inception
                        print('STARTING NEW STRIKE....{}'.format(strike) + '-' * 50)
                        sobj = attr[strike]
                        iv, delta, gamma, vega, vanna = float(sobj.iv), float(sobj.delta), float(sobj.gamma), float(sobj.vega), float(sobj.vanna)
                        print('model using sec_price = {}, strike = {}, r = {}, T = {}, q = {}, sigma = {} of type = {}'.format(security.price, sobj.strike_price, risk_free_rate, sobj.days_until_expiration/365, dividends[security.symbol], iv, 'CALL' if attr == security.expirations[expiration].calls else 'PUT'))
                        model = BlackSholesMerton(S=security.price, K=float(sobj.strike_price), r=risk_free_rate, T=float(sobj.days_until_expiration)/365, q=dividends[security.symbol], sigma=iv/100, option_type='CALL' if attr == security.expirations[expiration].calls else 'PUT')
                        
                        if gamma == 0:
                            gamma = model.Gamma
                            if np.isnan(gamma):
                                gamma = 0

                        premium = model.Premium

                        ## accounting for new TD NAN vars
                        if iv > 1:
                            premium = sobj.midpoint

                        print('premium was {}'.format(premium))
                        print('GOT THE GREEKS....{}, {}, {}, {}'.format(delta, gamma, vega, vanna))
                        try:
                            match_space = self.expirations[expiration].strikes
                        except KeyError:
                            print(self.expirations.keys())
                            match_space = None
                        match = None
                        if match_space is not None:
                            for feed_strike_object in match_space:
                                if float(sobj.strike_price) == float(feed_strike_object.strike_price):
                                    print('GOT MATCH......{}'.format(feed_strike_object.strike_price))
                                    match = feed_strike_object
                        if match is None:
                            callDDOI, putDDOI = 0, 0
                            # print('no match, grabbing yesterday')
                            #
                            # sql = 'SELECT dealer_directional_open_interest FROM DDOI WHERE underlying_symbol = ?' \
                            #           ' and expiration = ? and strike = ? and option_type = ? and isCurrent = 1'
                            # callDDOI = cursor.execute(sql, (security.symbol, expiration, float(strike), 'CALL')).fetchone()
                            # putDDOI = cursor.execute(sql, (security.symbol, expiration, float(strike), 'PUT')).fetchone()
                            # if callDDOI is None:
                            #     print(callDDOI)
                            #     callDDOI = 0
                            #     print(callDDOI)
                            # else:
                            #     callDDOI = callDDOI[0]
                            # if putDDOI is None:
                            #     print(putDDOI)
                            #     putDDOI = 0
                            #     print(putDDOI)
                            # else:
                            #     putDDOI = putDDOI[0]
                        else:
                            callDDOI, putDDOI = match.callDDOI, match.putDDOI

                        if attr == security.expirations[expiration].calls:
                            inception_tester_sql = """ SELECT quote_datetime FROM DDOI WHERE underlying_symbol = ? and expiration = ? and strike = ? and option_type = 'CALL' and isCurrent = 1"""
                            if strike_inception is False:
                                print('testing secondary.....')
                                cursor.execute(inception_tester_sql, (security.symbol, expiration, float(strike)))
                                if len(cursor.fetchall()) == 0:
                                    strike_inception = True
                                    print('New strike....inception special set to true')
                            if strike_inception:
                                print('OK...inserting inception sql now')
                                try:
                                    cursor.execute(inception_sql, (security.symbol, date_compiled, expiration, float(strike), 'CALL', round(premium, 4), int(callDDOI), int(security.expirations[expiration].calls[strike].openInterest), iv, delta, gamma, vega, vanna, 1))
                                except sqlite3.IntegrityError:
                                    # cursor.execute(inception_sql, (
                                    # security.symbol, date_compiled, expiration, float(strike), 'CALL', round(premium, 4),
                                    # int(security.expirations[expiration].calls[strike].openInterest), int(security.expirations[expiration].calls[strike].openInterest), iv,
                                    # delta, gamma, vega, vanna, 1))
                                    pass

                            else:
                                print('OK...update sql now')
                                try:
                                    cursor.execute(update_live_sql, (int(callDDOI), date_compiled, round(premium, 4), iv, delta, gamma, vega, vanna, int(security.expirations[expiration].calls[strike].openInterest),  expiration, float(strike), "CALL", self.underlying_symbol))

                                except sqlite3.IntegrityError:
                                    # cursor.execute(exeption_update_live_sql, (
                                    #  int(security.expirations[expiration].calls[strike].openInterest), date_compiled, round(premium, 4), iv, delta, gamma, vega, vanna,
                                    # int(security.expirations[expiration].calls[strike].openInterest), expiration,
                                    # float(strike), "CALL", self.underlying_symbol))
                                    pass


                        else:
                            inception_tester_sql = """ SELECT quote_datetime FROM DDOI WHERE underlying_symbol = ? and expiration = ? and strike = ? and option_type = 'PUT' and isCurrent = 1"""
                            if strike_inception is False:
                                print('testing secondary.....')
                                cursor.execute(inception_tester_sql, (security.symbol, expiration, float(strike)))
                                if len(cursor.fetchall()) == 0:
                                    strike_inception = True
                                    print('New strike....inception special set to true')

                            if strike_inception:
                                print('OK...inserting inception sql now')
                                try:
                                    cursor.execute(inception_sql, (
                                    security.symbol, date_compiled, expiration, float(strike), 'PUT', round(premium, 4), int(putDDOI),
                                    int(security.expirations[expiration].puts[strike].openInterest), iv, delta, gamma, vega, vanna,
                                    1))
                                except sqlite3.IntegrityError:
                                    # cursor.execute(inception_sql, (
                                    #     security.symbol, date_compiled, expiration, float(strike), 'PUT', round(premium, 4),
                                    #     int(security.expirations[expiration].puts[strike].openInterest),
                                    #     int(security.expirations[expiration].puts[strike].openInterest), iv, delta, gamma,
                                    #     vega, vanna,
                                    #     1))
                                    pass

                            else:
                                try:
                                    print('OK...update sql now')
                                    cursor.execute(update_live_sql, (int(putDDOI), date_compiled, round(premium, 4), iv, delta, gamma, vega, vanna, int(security.expirations[expiration].puts[strike].openInterest),  expiration, float(strike), "PUT", self.underlying_symbol))
                                except sqlite3.IntegrityError:
                                    # print(callDDOI, putDDOI)
                                    # print(security.expirations[expiration].puts[strike].openInterest)
                                    #
                                    # cursor.execute(exeption_update_live_sql, (
                                    #  int(security.expirations[expiration].puts[strike].openInterest), date_compiled, round(premium, 4), iv, delta, gamma, vega, vanna,
                                    # int(security.expirations[expiration].puts[strike].openInterest), expiration,
                                    # float(strike), "PUT", self.underlying_symbol))
                                    pass

        self.delete_expired(cursor_con=cursor, date_compiled=date_compiled)

        # COPY EOD table and Store with isCurrent = 0
        copy_eod_sql = 'SELECT * FROM EOD WHERE underlying_symbol = ? and isCurrent = 1'
        cursor.execute(copy_eod_sql, (self.underlying_symbol,))

        memory = [list(item) for item in cursor]
        adjusted = []
        for item in memory:
            item[-1] = 0
            adjusted.append(tuple(item))

        re_insert_sql = "INSERT INTO EOD VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        for item in adjusted:
            cursor.execute(re_insert_sql, item)
        print('just completed EOD map funtion!!!!')



        # UPDATE EOD table WHERE is CURRENT = 1



        update_EOD_stats_sql = "UPDATE EOD SET underlying_price = ? ,quote_datetime= ?, dealer_delta_notional = ? , dealer_gamma_notional = ?, vega_notional = ?, dealer_vanna_notional = ?, atm_calls_bought = ?, atm_calls_sold = ?, otm_calls_bought = ? , otm_calls_sold = ?, itm_calls_bought = ?, itm_calls_sold = ?, atm_puts_bought = ?, atm_puts_sold = ?, otm_puts_bought = ? , otm_puts_sold = ?, itm_puts_bought = ?, itm_puts_sold = ? WHERE isCurrent = 1 and underlying_symbol = ?"
        inception_sql = """INSERT INTO EOD VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        test_Sql = 'SELECT * FROM EOD WHERE underlying_symbol = ? and isCurrent = 1'
        test = cursor.execute(test_Sql, (self.underlying_symbol,)).fetchall()
        if len(test) == 0:
            inception = True
        else:
            inception = False

        summon_sql = 'SELECT dealer_directional_open_interest, delta, gamma, vega, vanna FROM DDOI WHERE underlying_symbol = ? and isCurrent = 1'
        cursor.execute(summon_sql, (self.underlying_symbol,))
        dealer_delta_notional = 0
        dealer_gamma_notional = 0
        vega_notional = self.notional_vega
        dealer_vanna_notional = 0


        for ddoi, delta, gamma, vega, vanna in cursor:

            try:
                if delta not in ('inf', '-inf', 'nan'):
                    print('adding delta' + '{}'.format(ddoi * delta * 100 * security.price))
                    dealer_delta_notional += (ddoi * delta * 100 * security.price)
            except TypeError:
                pass
            try:
                if gamma not in ('inf', '-inf', 'nan'):
                    print('adding gamma' + '{}'.format(ddoi * gamma * 100 * security.price))
                    dealer_gamma_notional += (ddoi * gamma * 100 * security.price)
            except TypeError:
                pass
            # try:
            #     if vega not in ('inf', '-inf', 'nan'):
            #         vega_notional += (ddoi * vega * 100 * security.price)
            # except TypeError:
            #     pass
            try:
                if vanna not in ('inf', '-inf', 'nan'):
                    dealer_vanna_notional += (ddoi * vanna * 100 * security.price)
            except TypeError:
                pass

        dealer_vanna_notional = dealer_vanna_notional / 15
        if inception:
            cursor.execute(inception_sql, (security.symbol, date_compiled, security.price, dealer_delta_notional, dealer_gamma_notional, vega_notional, dealer_vanna_notional, self.percent_ATM_calls_bought, self.percent_ATM_calls_sold, self.percent_OTM_calls_bought, self.percent_OTM_calls_sold, self.percent_ITM_calls_bought, self.percent_ITM_calls_sold, self.percent_ATM_puts_bought, self.percent_ATM_puts_sold, self.percent_OTM_puts_bought, self.percent_OTM_puts_sold, self.percent_ITM_puts_bought, self.percent_ITM_puts_sold, 1))
        else:
            cursor.execute(update_EOD_stats_sql, (security.price, date_compiled, dealer_delta_notional, dealer_gamma_notional, vega_notional, dealer_vanna_notional, self.percent_ATM_calls_bought, self.percent_ATM_calls_sold, self.percent_OTM_calls_bought, self.percent_OTM_calls_sold, self.percent_ITM_calls_bought, self.percent_ITM_calls_sold, self.percent_ATM_puts_bought, self.percent_ATM_puts_sold, self.percent_OTM_puts_bought, self.percent_OTM_puts_sold, self.percent_ITM_puts_bought, self.percent_ITM_puts_sold, security.symbol))
        db.commit()

    def __str__(self):
        print(self.aggregator)
        return ''

    def get_atm_vol(self, sec_obj):

        pass


    def to_aggregator(self, aggregator: Aggregator):
        payload = self.summation_strikes, self.expirations
        aggregator.accept_payload(payload=payload)

    def get_aggregator(self):
        return self.aggregator

    def get_liquidity_tracker(self):
        return self.liquidity_tracker

    def plot_strike_gamma(self):
        fig, ax = plt.subplots()
        x, y = [], []
        iteration = self.strikegamma.strike_gamma.keys()
        iteration = [float(item) for item in iteration]
        for strike in sorted(iteration):
            x.append(str(float(strike)) + '.0')
            y.append(self.strikegamma.strike_gamma[str(strike) + '00'])
        ax.bar(x, y, color='black', edgecolor='white')
        ax.tick_params(axis='x', labelrotation=90)
        return fig


class Liquidity:

    def __init__(self):

        self.expirations = {}

    @staticmethod
    def initialize_data_structure(trades: list) -> dict:
        used = []
        used_strike_combination = []
        expirations = {}
        for trade in trades:
            if trade.expiration not in used:
                used.append(trade.expiration)
                tracker = ExpiryTracker(date=trade.expiration)
                expirations[trade.expiration] = tracker
            if (trade.expiration, trade.strike) not in used_strike_combination:
                used_strike_combination.append((trade.expiration, trade.strike))
                exp = expirations[trade.expiration]
                exp.add_strike(strike=StrikeTracker(strike_price=trade.strike))

        return expirations

    def accept_new_trades(self, trades: list) -> None:
        self.merge(expirations_old=self.expirations, expirations_new=self.initialize_data_structure(trades=trades))
        for trade in trades:
            strike_proper = self.expirations[trade.expiration].strikes[trade.strike]
            strike_proper.accept_trade(trade=trade)

    @staticmethod
    def merge(expirations_old: dict, expirations_new: dict) -> None:
        for expiry in expirations_new.keys():
            if expiry in expirations_old.keys():
                exp_object = expirations_new[expiry]
                for strike in exp_object.strikes.keys():
                    if strike in expirations_old[expiry].strikes.keys():
                        strike_obj = expirations_new[expiry].strikes[strike]
                        expirations_old[expiry].strikes[strike].time_stamps.update(strike_obj.time_stamps)
                    else:
                        expirations_old[expiry].strikes[strike] = expirations_new[expiry].strikes[strike]
            else:
                expirations_old[expiry] = expirations_new[expiry]

    def get_line_points(self, expiry: str, strike: str, date_time_low, date_time_high, option_type='CALL') -> tuple:
        try:
            assert strike in self.expirations[expiry].strikes.keys(), 'NOT A VALID STRIKE INPUT {}'.format(strike)
            x = [key for key in sorted(self.expirations[expiry].strikes[strike].time_stamps.keys())]
            y_bid_ask = []
            x_new = x.copy()

            for value in x:
                # print(value)
                try:
                    bid = int(self.expirations[expiry].strikes[strike].time_stamps[value][option_type]['bid_size'])
                    ask = int(self.expirations[expiry].strikes[strike].time_stamps[value][option_type]['ask_size'])
                except KeyError:
                    x_new.remove(value)
                    continue
                else:
                    # print('date_low = {}, type({})'.format(date_time_low, type(date_time_low)))
                    date_time_low_test = mdates.date2num(datetime.datetime.strptime(date_time_low, '%Y-%m-%d %H:%M:%S.%f'))
                    date_time_high_test = mdates.date2num(datetime.datetime.strptime(date_time_high, '%Y-%m-%d %H:%M:%S.%f'))
                    test_x = mdates.date2num(datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f'))
                    if date_time_low_test <= test_x <= date_time_high_test:
                        y_bid_ask.append((bid, ask))
                    else:
                        x_new.remove(value)
                        continue
        except AssertionError:
            return None, None

        return x_new, y_bid_ask

    def plot(self, expiry: str, strike: str, date_time_low, date_time_high, option_type='CALL', format_date_time=True) -> plt.Figure:

        fig = plt.figure(figsize=(15, 5))
        ax1 = fig.add_axes([0.1, 0.3, 0.8, 0.65])
        ax2 = fig.add_axes([0.1, 0.05, 0.8, 0.23])
        try:
            put_or_call = option_type

            x, y = self.get_line_points(expiry=expiry, strike=strike, date_time_low=date_time_low, date_time_high=date_time_high, option_type=put_or_call)

            xs = x
            y_bid = [value[0] for value in y]
            y_ask = [value[1] for value in y]

            if format_date_time is True:
                xs = list(map(lambda x: datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f'), xs))
                xs = list(map(lambda x: mdates.date2num(x), xs))


            ax1.plot(xs, y_bid, label='Bid size', lw=3, color='#f2cf61', alpha=0.5)
            ax1.plot(xs, y_ask, label='Ask size', lw=3, color='#1a8cf4', alpha=0.5)
            ax1.xaxis.set_major_formatter(mdates.DateFormatter(''))
            ax1.legend(loc='upper left')

            x, y = self.get_bid_ask_prices(expiry=expiry, strike=strike, date_time_low=date_time_low, date_time_high=date_time_high, option_type=put_or_call)
            xs = x
            y_bid = [value[0] for value in y]
            y_ask = [value[1] for value in y]
            if format_date_time is True:
                xs = list(map(lambda x: datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f'), xs))
                xs = list(map(lambda x: mdates.date2num(x), xs))
            new_ax = ax1.twinx()
            new_ax.plot(xs, y_bid, color='green', ls='--', alpha=1.0, label='Bid')
            new_ax.plot(xs, y_ask, color='#c5150b', ls='--', alpha=1.0, label='Ask')
            new_ax.legend(loc='upper right')
            self.plot_trades_overlay(axis=ax2, expiry=expiry, strike=strike, date_time_low=date_time_low, date_time_high=date_time_high, option_type=put_or_call,
                                     format_date_time=format_date_time)
        except TypeError:
            pass

        return fig

    def get_trade_points(self, expiry: str, strike: str, date_time_low: str, date_time_high: str, option_type='CALL') -> tuple:

        strike = str(strike)
        x = [key for key in sorted(self.expirations[expiry].strikes[strike].time_stamps.keys())]
        y = []
        x_new = x.copy()
        for value in x:
            try:

                length = len(self.expirations[expiry].strikes[strike].time_stamps[value][option_type]['trade_sizes'])
            except KeyError:

                x_new.remove(value)
                continue
            else:
                date_time_low_test = mdates.date2num(datetime.datetime.strptime(date_time_low, '%Y-%m-%d %H:%M:%S.%f'))
                date_time_high_test = mdates.date2num(datetime.datetime.strptime(date_time_high, '%Y-%m-%d %H:%M:%S.%f'))
                test_x = mdates.date2num(datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f'))
                if date_time_low_test <= test_x <= date_time_high_test:
                    if length == 1:
                        y.append(self.expirations[expiry].strikes[strike].time_stamps[value][option_type]['trade_sizes'][0])
                    else:
                        points = [value for value in
                                  self.expirations[expiry].strikes[strike].time_stamps[value][option_type]['trade_sizes']]
                        y.append(points)
                else:
                    x_new.remove(value)
        return x_new, y

    def plot_trades_overlay(self, axis, expiry: str, strike: str, date_time_low: str, date_time_high: str, option_type="CALL", format_date_time=True) -> None:
        try:
            assert expiry in self.expirations.keys(), 'NOT A VALID EXPIRY'
            assert strike in self.expirations[expiry].strikes.keys(), 'NOT A VALID STRIKE'

            contract_type = option_type
            x, y = self.get_trade_points(expiry=expiry, strike=strike, date_time_low=date_time_low, date_time_high=date_time_high, option_type=contract_type)

            plotting_heirarchies = {}
            try:
                max_ys = max([len(y[x.index(x_val)]) for x_val in x if type(y[x.index(x_val)]) is not int])
            except ValueError:
                max_ys = 1

            def get_value(input) -> tuple:
                if type(input) is tuple:
                    return input
                elif type(input) is list:
                    return input[0]

            plotting_heirarchies[1] = [x_val for x_val in x], [get_value(y_val) for y_val in y]
            for i in range(2, max_ys + 1):
                plotting_heirarchies[i] = [x_val for x_val in x if type(y[x.index(x_val)]) is not tuple
                                           and len(y[x.index(x_val)]) >= i],\
                                          [y_val[i-1] for y_val in y if type(y_val) is not tuple and len(y_val) >= i]

            last_xs = None
            last_ys = None
            bottom = None

            for h in plotting_heirarchies:
                new_x, new_y = plotting_heirarchies[h]

                isfinal = False
                try:
                    next = plotting_heirarchies[h + 1]

                except KeyError:
                    isfinal = True

                finally:
                    old_bottom = bottom
                    y_counter = 0

                    if not isfinal:
                        if h != 1:

                            next_bottom = []
                            for y_val in new_y:
                                associated_x = new_x[y_counter]
                                if associated_x in plotting_heirarchies[h+1][0]:
                                    x_position = last_xs.index(associated_x)
                                    next_bottom.append(y_val[0] + old_bottom[x_position])
                                else:
                                    next_bottom.append('N/A')
                                y_counter += 1
                        else:
                            next_bottom = []
                            for y_val in new_y:
                                if new_x[y_counter] in plotting_heirarchies[h+1][0]:
                                    next_bottom.append(y_val[0])
                                else:
                                    next_bottom.append('N/A')
                                y_counter += 1
                    else:
                        next_bottom = None

                    last_xs = new_x
                    if format_date_time is True:
                        new_x = list(map(lambda x: datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f'), new_x))
                        new_x = list(map(lambda x: mdates.date2num(x), new_x))

                    if bottom is not None:
                        plotting_bottom = [value for value in bottom if value != 'N/A']
                        assert len(new_x) == len(new_y) == len(plotting_bottom),\
                            'BOTTOMS ARE NOT EQUAL in iteration: {} lenx= {}, leny = {}, lenb={}'.format(
                                h, len(new_x), len(new_y), len(plotting_bottom))
                    else:
                        plotting_bottom = bottom

                    # split into buys and sells
                    buyx, buyy, buyb = [], [], []
                    sellx, selly, sellb = [], [], []
                    nodirx, nodiry, nodirb = [], [], []
                    for y_val in new_y:
                        if y_val[2] == 'BUY':
                            if plotting_bottom is not None:
                                buyb.append(plotting_bottom[new_y.index(y_val)])
                            buyx.append(new_x[new_y.index(y_val)])
                            buyy.append(y_val)
                        elif y_val[2] == 'SELL':
                            if plotting_bottom is not None:
                                sellb.append(plotting_bottom[new_y.index(y_val)])
                            sellx.append(new_x[new_y.index(y_val)])
                            selly.append(y_val)
                        elif y_val[2] == 'NONE':
                            if plotting_bottom is not None:
                                nodirb.append(plotting_bottom[new_y.index(y_val)])
                            nodirx.append(new_x[new_y.index(y_val)])
                            nodiry.append(y_val)

                    if plotting_bottom is None:
                        buyb, sellb, nodirb = None, None, None

                    #plot buys
                    plotting_ys = [int(y_val[0]) for y_val in buyy]
                    axis.bar(buyx, plotting_ys, alpha=1.0, width=0.001, bottom=buyb, edgecolor='black', color='#45f60e' )

                    #plot sells
                    plotting_ys = [int(y_val[0]) for y_val in selly]
                    axis.bar(sellx, plotting_ys, alpha=1.0, width=0.001, bottom=sellb, edgecolor='black', color='#ff0900')

                    #plot uninferred
                    plotting_ys = [int(y_val[0]) for y_val in nodiry]
                    axis.bar(nodirx, plotting_ys, alpha=1.0, width=0.001, bottom=nodirb, edgecolor='black', color='grey')

                    axis.grid(axis='y', color='black', ls='--')

                    if format_date_time is True:
                        axis.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                    if not isfinal:
                        bottom = next_bottom
                    last_ys = new_y
        except AssertionError:
            pass

    def get_bid_ask_prices(self, expiry: str, strike: str, date_time_low: str, date_time_high: str, option_type="CALL", format_date_time=True):
        assert strike in self.expirations[expiry].strikes.keys(), 'NOT A VALID STRIKE INPUT'
        x = [key for key in sorted(self.expirations[expiry].strikes[strike].time_stamps.keys())]
        y_bid_ask = []
        x_new = x.copy()

        for value in x:
            # print(value)
            try:
                bid = float(self.expirations[expiry].strikes[strike].time_stamps[value][option_type]['bid'])
                ask = float(self.expirations[expiry].strikes[strike].time_stamps[value][option_type]['ask'])
            except KeyError:
                x_new.remove(value)
                continue
            else:
                # print('date_low = {}, type({})'.format(date_time_low, type(date_time_low)))
                date_time_low_test = mdates.date2num(datetime.datetime.strptime(date_time_low, '%Y-%m-%d %H:%M:%S.%f'))
                date_time_high_test = mdates.date2num(
                    datetime.datetime.strptime(date_time_high, '%Y-%m-%d %H:%M:%S.%f'))
                test_x = mdates.date2num(datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f'))
                if date_time_low_test <= test_x <= date_time_high_test:
                    y_bid_ask.append((bid, ask))
                else:
                    x_new.remove(value)
                    continue

        return x_new, y_bid_ask

    def to_gui(self):

        self.main_window = tk.Tk()

        self.main_window.geometry('950x500')
        frame = ToolFrame(parent=self.main_window, ltracker=self, first=True)

        self.main_window.mainloop()

    def add_frame(self):
        new = ToolFrame(parent=self.main_window, ltracker=self)

    def plot_nanex_style(self):
        delta_trades = {}
        for exp in sorted(self.expirations.keys()):
            for strike in sorted(self.expirations[exp].strikes.keys()):
                for stamp in sorted(self.expirations[exp].strikes[strike].time_stamps.keys()):
                    working_dic = self.expirations[exp].strikes[strike].time_stamps[stamp]
                    delta = 0
                    for cp in working_dic:
                        delta += sum([trade[3] for trade in working_dic[cp]['trade_sizes']])
                    try:
                        delta_trades[stamp] += delta
                    except KeyError:
                        delta_trades[stamp] = delta

        fig, ax = plt.subplots()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        xs = list(map(lambda x: datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f'),
                      [key for key in sorted(delta_trades.keys())]))
        ys = [delta_trades[key] for key in sorted(delta_trades.keys())]
        ax.plot(xs, ys, color='black', alpha=0.35)
        ax.scatter(xs, ys, color='white', edgecolor='black')
        return fig


class ToolFrame:

    def __init__(self, parent, ltracker: Liquidity, first=False):
        self.parent = parent
        self.tracker = ltracker
        self.input_frame = tk.Frame(master=parent)
        self.graph_frame = tk.Frame(master=parent)
        self.input_frame.pack(expand='true', fill='both')
        self.graph_frame.pack(expand='true', fill='both')

        self.expvar = tk.StringVar()
        self.expvar.set('EXPIRATION')

        self.strikevar = tk.StringVar()
        self.strikevar.set('STRIKE')

        choices = tuple(sorted(self.tracker.expirations.keys()))

        strike_choices = []
        for exp in ltracker.expirations:
            for strike in ltracker.expirations[exp].strikes.keys():
                if strike not in strike_choices:
                    strike_choices.append(strike)
        strike_choices = tuple(sorted(strike_choices))

        self.expiry_drop_down = tk.OptionMenu(self.input_frame, self.expvar, *choices)

        self.strike_drop_down = tk.OptionMenu(self.input_frame, self.strikevar, *strike_choices)
        self.low_time_box = tk.Entry(master=self.input_frame)
        self.high_time_box = tk.Entry(master=self.input_frame)
        self.var1 = tk.IntVar()
        self.put_or_call = tk.Checkbutton(master=self.input_frame, variable=self.var1, text='CALL/PUT')

        self.expiry_drop_down.grid(row=0, column=0)
        self.strike_drop_down.grid(row=0, column=1)
        self.low_time_box.grid(row=0, column=2)
        self.high_time_box.grid(row=0, column=3)
        self.put_or_call.grid(row=0, column=4)

        plot_button = tk.Button(master=self.input_frame, command=self.plot_tk, text='GRAPH')
        plot_button.grid(row=0, column=5)

        if first is True:
            self.add_button = tk.Button(master=self.input_frame, command=self.tracker.add_frame, text='+')
            self.add_button.grid(row=0, column=6)

    def plot_tk(self):
        self.graph_frame.destroy()
        self.graph_frame = tk.Frame(master=self.parent)
        self.graph_frame.pack(fill='both', expand='true')
        put_or_call = 'CALL' if self.var1.get() == 1 else 'PUT'
        # print(put_or_call)
        figure = self.tracker.plot(expiry=self.expvar.get(), strike=self.strikevar.get(),
                           date_time_low=self.low_time_box.get(), date_time_high=self.high_time_box.get(),
                           option_type=put_or_call, format_date_time=True)

        canvas = FigureCanvasTkAgg(figure=figure, master=self.graph_frame)
        canvas.get_tk_widget().pack(fill='both', expand='true')
        canvas.draw()

        # toolbar = NavigationToolbar2Tk(canvas, self.graph_frame)
        # toolbar.update()
        # canvas._tkcanvas.pack()


class StrikeTracker:

    def __init__(self, strike_price: str):
        self.strike_price = strike_price
        self.time_stamps = {}

    def initialize_time_stamp(self, stamp: str, trade: Trade) -> None:
        sum_bid_size = sum([int(trade.by_exchange[exchange][0]) for exchange in trade.by_exchange if trade.by_exchange[exchange][1] == trade.best_bid])
        sum_ask_size = sum([int(trade.by_exchange[exchange][2]) for exchange in trade.by_exchange if trade.by_exchange[exchange][3] == trade.best_ask])

        try:
            self.time_stamps[stamp][trade.option_type] =\
                {'bid': trade.best_bid, 'ask': trade.best_ask,
                 'bid_size': sum_bid_size, 'ask_size': sum_ask_size, 'count': 1, 'trade_sizes': [(trade.trade_size, trade.sequence_number, trade.inference, trade.delta) ]}
        except KeyError:
            self.time_stamps[stamp] = {'{}'.format(trade.option_type):
                                           {'bid': trade.best_bid, 'ask': trade.best_ask,
                                            'bid_size': sum_bid_size, 'ask_size': sum_ask_size, 'count': 1, 'trade_sizes': [(trade.trade_size, trade.sequence_number, trade.inference, trade.delta)]}, }

    def add_time_stamp(self, stamp: str, trade: Trade) -> None:
        proper_stamp = self.time_stamps[stamp][trade.option_type]
        sum_bid_size = sum([int(trade.by_exchange[exchange][0]) for exchange in trade.by_exchange if trade.by_exchange[exchange][1] == trade.best_bid])
        sum_ask_size = sum([int(trade.by_exchange[exchange][2]) for exchange in trade.by_exchange if trade.by_exchange[exchange][3] == trade.best_ask])
        proper_stamp['count'] += 1
        proper_stamp['bid_size'] = (((proper_stamp['bid_size'] * (proper_stamp['count'] - 1)) + sum_bid_size)) / proper_stamp['count']
        proper_stamp['ask_size'] = (((proper_stamp['ask_size'] * (proper_stamp['count'] - 1)) + sum_ask_size)) / proper_stamp['count']
        proper_stamp['trade_sizes'].append((trade.trade_size, trade.sequence_number, trade.inference, trade.delta))

    def accept_trade(self, trade: Trade) -> None:
        if trade.quote_datetime in self.time_stamps.keys():
                if trade.option_type in self.time_stamps[trade.quote_datetime].keys():
                    self.add_time_stamp(stamp=trade.quote_datetime, trade=trade)
                else:
                    self.initialize_time_stamp(stamp=trade.quote_datetime, trade=trade)
        else:
            self.initialize_time_stamp(stamp=trade.quote_datetime, trade=trade)


class ExpiryTracker:

    def __init__(self, date: str):
        self.expiration_date = date
        self.strikes = {}

    def add_strike(self, strike: StrikeTracker) -> None:
        self.strikes[strike.strike_price] = strike


class StrikeGamma:

    def __init__(self,):
        self.strike_gamma = {}

    def accept_strike_gamma(self, trades):
        for trade in trades:
            try:
                if trade.inference == 'BUY':
                    self.strike_gamma[trade.strike] -= trade.gamma
                elif trade.inference == 'SELL':
                    self.strike_gamma[trade.strike] += trade.gamma
            except KeyError:
                if trade.inference == 'BUY':
                    self.strike_gamma[trade.strike] = -trade.gamma
                elif trade.inference == 'SELL':
                    self.strike_gamma[trade.strike] = trade.gamma

    def summon_strike_gamma(self, database):
        pass


# ------------------NEW CLASS ADDITIONS JAN 2021 - VOl Surface Infrastructure-----------------------


class StrikeHolder:

    def __init__(self, strike):
        self.strike_price = strike
        self.tally = []
        self.volatility = None
        pass

    def add_trade(self, trade:Trade):

        self.tally.append(trade)
        self.set_iv()

    def set_iv(self):
        self.volatility = np.mean([trade.volatility for trade in self.tally])


class ExpirationHolder:

    def __init__(self, expiration: str):
        self.expiration_date = expiration
        self.strikes = {}
        pass

    def add_strike(self, holder: StrikeHolder):
        self.strikes[holder.strike_price] = holder


class TimeStamp:

    def __init__(self, time: str):
        self.time = time
        self.expirations = {}

    def add_expiration(self, holder: ExpirationHolder):
        self.expirations[holder.expiration_date] = holder


class TimeStampArchive:

    def __init__(self, trades: list):
        self.trades = trades
        self.timestamps = {}
        self.underlying_symbol = self.trades[10].underlying

        for trade in self.trades:
            if trade.quote_datetime not in self.timestamps.keys():
                timestamp = TimeStamp(time=trade.quote_datetime)
                expiration_holder = ExpirationHolder(expiration=trade.expiration)
                strike_holder = StrikeHolder(strike=trade.strike)
                strike_holder.add_trade(trade=trade)
                expiration_holder.add_strike(holder=strike_holder)
                timestamp.add_expiration(holder=expiration_holder)

                self.timestamps[trade.quote_datetime] = timestamp

            elif trade.expiration not in self.timestamps[trade.quote_datetime].expirations.keys():

                timestamp = self.timestamps[trade.quote_datetime]
                expiration_holder = ExpirationHolder(expiration=trade.expiration)
                strike_holder = StrikeHolder(strike=trade.strike)
                strike_holder.add_trade(trade=trade)
                expiration_holder.add_strike(holder=strike_holder)
                timestamp.add_expiration(holder=expiration_holder)

            elif trade.strike not in self.timestamps[trade.quote_datetime].expirations[trade.expiration].strikes.keys():

                expiration_holder = self.timestamps[trade.quote_datetime].expirations[trade.expiration]
                strike_holder = StrikeHolder(strike=trade.strike)
                strike_holder.add_trade(trade=trade)
                expiration_holder.add_strike(holder=strike_holder)

            else:

                strike_holder = self.timestamps[trade.quote_datetime].expirations[trade.expiration].strikes[trade.strike]
                strike_holder.add_trade(trade=trade)


class CurveArchive:

    def __init__(self, archive: TimeStampArchive):

        # takes previously constructed catalogue of trades at times
        self.archive = archive
        self.curves = {}

        self.get_curves()

        for curve in sorted(self.curves):
            curve_object = self.curves[curve]
            print("__________________{}___________________".format(curve_object.expiry))
            for time_stamp in sorted(self.archive.timestamps):
                if curve in self.archive.timestamps[time_stamp].expirations:
                    batch = self.get_batch(timestamp=time_stamp, expiry=curve)
                    curve_object.process_batch(trade_batch=batch, time_stamp=time_stamp)


    # ------------------------------------------------------------------------------------------------
                    # multi_CORE STUFF - COMMENT IN for multiprocessing, comment out
                    # and see class VolatilityCurve in process_batch method for single processing

            # splits = np.array_split(np.array([time_stamp for time_stamp in sorted(self.archive.timestamps)]), 6) #CORE SPLITS
            #
            # splits = [s for s in splits]
            # print('SPLITS = {}'.format(splits))
            #
            # with concurrent.futures.ProcessPoolExecutor() as ex:
            #     g = ex.map(curve_object.execute_curve_sequence, splits)
            #
            # P, S = {}, {}
            # for poly_log, sabr_log in g:
            #     P.update(poly_log)
            #     S.update(sabr_log)
            # curve_object.set_chronolog(log=P)
            # curve_object.set_sabrlog(log=S)

    # ------------------------------------------------------------------------------------------------


    def get_batch(self, timestamp, expiry):
        print('getting_batch - {} - {}'.format(expiry, timestamp))
        batch = []
        try:
            for strike in self.archive.timestamps[timestamp].expirations[expiry].strikes:
                strike_obj = self.archive.timestamps[timestamp].expirations[expiry].strikes[strike]
                batch.extend(strike_obj.tally)
        except KeyError:
            pass

        return batch

    def get_curves(self):
        expirations = []
        for timestamp in self.archive.timestamps:
            for expiration in self.archive.timestamps[timestamp].expirations:
                if expiration not in expirations:
                    expirations.append(expiration)
        for expiration in expirations:
            self.curves[expiration] = VolatilityCurve(expiry=expiration, stamp_archive=self.archive)


class VolatilityCurve:

    def __init__(self, expiry, stamp_archive: TimeStampArchive):

        self.stamp_archive = stamp_archive

        self.underlying_symbol = self.stamp_archive.underlying_symbol

        self.expiry = expiry

        self.T = self._get_T()

        self.chronolog = {}

        self.sabr_log = {}

        self.active_trade_chronolog = {}

        self.active_trades = []

        self.running_variance = None

        self.var_threshold = .2

        self.polynomial = None

        self.modulator = Modulator(Curve=self)

# new function to weed out dud trades. - experimental
    def filter_for_duds(self, trades):
        returnable_trades = []
        # ivdic = dict()
        # for trade in trades:
        #     if trade.strike not in ivdic.keys():
        #         ivdic[trade.strike] = [trade.fill_iv, ]
        #     else:
        #         list = ivdic[trade.strike]
        #         list.append(trade.fill_iv)
        #         ivdic[trade.strike] = list

        for trade in trades:
            if trade.fill_iv != 0:
                returnable_trades.append(trade)
        return returnable_trades

    def set_chronolog(self, log: dict):
        self.chronolog = log

    def set_sabrlog(self, log: dict):
        self.sabr_log = log

    def process_curve(self, trades, time_stamp, sabr_log, poly_log):

        poly = self.fit_polynomial(trades=trades)

        poly_log[time_stamp] = poly
        print("Processed Batch ~ {} / {}".format(time_stamp, poly))
        sabr_log[time_stamp] = self.fit_SABR(trades=trades)

    def execute_curve_sequence(self, timestamps):
        sabr_log, poly_log = dict(), dict()
        for time_stamp in timestamps:
            try:
                trades = self.active_trade_chronolog[time_stamp]
                self.process_curve(trades=trades, time_stamp=time_stamp, sabr_log=sabr_log, poly_log=poly_log)
            except KeyError:
                continue
        return poly_log, sabr_log

    def _get_T(self):
        date = list(self.stamp_archive.timestamps.keys())[0]
        date = date.split(' ')[0]

        now = datetime.datetime.strptime(date, '%Y-%m-%d')
        future = datetime.datetime.strptime('{} 16:00:00.000'.format(self.expiry), '%Y-%m-%d %H:%M:%S.%f')

        diff = future - now

        print('T = {}'.format(diff.total_seconds() / (365 * 24 * 60 * 60)))

        return diff.total_seconds() / (365 * 24 * 60 * 60)

    def process_batch(self, trade_batch, time_stamp):

        # for trade in self.active_trades:
        #     print('decaying_Curve = {}'.format(self.check_for_newer_trade(trade=trade)))
        #     trade.project_to_time(time_stamp=time_stamp, trigger=self.check_for_newer_trade(trade=trade))

        # self.active_trades.extend([CurveTrade(trade=trade, life_span=10) for trade in trade_batch if trade.trade_iv != 0])

        print('PROCESSING MODULATOR', '*' * 100)

        updated_trades, weighed, sabr, polynomial = self.modulator.modulate(current_trades=self.active_trades, proposed_additions=trade_batch, new_time_stamp=time_stamp)
        print(self.modulator)
        print('*' * 100)

        # self.check_variance_and_weigh()

        # self.polynomial = self.fit_polynomial(trades=self.active_trades)

        # self.chronolog[time_stamp] = self.polynomial
        self.chronolog[time_stamp] = polynomial
        # self.active_trade_chronolog[time_stamp] = self.active_trades.copy()
        self.active_trade_chronolog[time_stamp] = updated_trades
        self.active_trades = updated_trades.copy()
        self.purge()

        # self.sabr_log[time_stamp] = self.fit_SABR(trades=self.active_trades)
        self.sabr_log[time_stamp] = sabr


        print("Processed Batch ~ {} / {}".format(time_stamp, self.polynomial))

    def fit_polynomial(self, trades):
        print('WEIGHING - LENGTH OF TRADES = {}'.format(len(trades)))


        # weighted = self.weigh(self.active_trades)
        filtered = self.discriminate_at_the_money(trades)
        weighted = self.weigh(filtered)

        x, y = [item[0] for item in weighted], [item[1] for item in weighted]

        if len(x) == 0:
            x, y = [1], [1]

        print('FITTING TO {}'.format([trade.fill_iv for trade in trades]))
        P = np.polynomial.polynomial.polyfit(x, y, deg=6)
        return np.polynomial.polynomial.Polynomial(P)

    def get_b(self):
        symbol = self.find_symbol()
        if dividends[symbol] == 0:
            b = risk_free_rate
        else:
            b = risk_free_rate - dividends[symbol]
        return b

    def find_symbol(self):

        return self.underlying_symbol

    def fit_SABR(self, trades):
        return_type = None

        try:
            # filtered = self.discriminate_at_the_money(trades=trades)
            weighted_trades = self.weigh(trades=trades)
            averaged, spot, forward = self.get_arrays(weighted_trades)
            model = SABR(f=forward, t=self.T)
            model.fit_parameters(x_data=[item[0] for item in averaged], y_data=[item[1] for item in averaged])
            print('JUST fit SABR model')
            print(model)
            return_type = model
        except (TypeError, RuntimeError, ValueError):
            pass

        return return_type

    def get_arrays(self, trades):
        points = dict()
        for trade in trades:
            if trade not in points.keys():
                points[trade[0]] = trade[1]
            else:
                L = points[trade[0]]
                L.append(trade[1])
        averaged = [(k, np.mean(points[k])) for k in points.keys()]
        spot = sorted([trade for trade in self.active_trades], key=lambda x: x.age)[0].underlying_price
        forward = self.forward_price(spot=spot, )
        return averaged, spot, forward

    def forward_price(self, spot):
        print('CALCULATING FORWARD PRICE, SPOT = {}, F = {}'.format(spot, spot * np.exp((self.get_b() - risk_free_rate) * self.T)))
        return spot * np.exp((self.get_b() - risk_free_rate) * self.T)

    def weigh(self, trades: list) -> list:
        multiples = []
        for trade in trades:
            pair = (float(trade.strike), float(trade.fill_iv))
            if trade.fill_iv >= 0.00:
                for i in range(trade.weight):
                    multiples.append(pair)
        return multiples

    def purge(self):
        for trade in self.active_trades:
            if trade.weight <= 0:
                self.active_trades.remove(trade)

    def calculate_running_variance(self, set_size):
        last_set = []
        for trade in reversed(sorted(self.active_trades, key=lambda x: x.time_stamp)):
            if len(last_set) < set_size:
                last_set.append(trade)
        return np.std([trade.fill_iv for trade in last_set])

    def check_variance_and_weigh(self):
        last = self.running_variance
        self.running_variance = self.calculate_running_variance(set_size=20)
        if last is not None:
            var_jump = abs((self.running_variance - last) / last)
            print('VAR JUMP = {}'.format(var_jump * 100))

            if var_jump > self.var_threshold:
                for trade in self.active_trades:
                    trade.adjust_decay_rate(1)

    def discriminate_at_the_money(self, trades):
        underlying_price = sorted([trade for trade in trades], key=lambda x: x.age)[0].underlying_price
        filtered = []

        margin = underlying_price * .2
        lower_bound, upper_bound = underlying_price - margin, underlying_price + margin

        for trade in trades:
            if lower_bound < trade.strike < upper_bound:
                filtered.append(trade)

        return filtered

    def plot_curve_progression(self):
        generator = self.stamp_generator()
        # frames = len([item for item in generator])
        # generator = self.stamp_generator()

        fig = plt.figure()
        ax = plt.axes(xlim=(3500, 4500), ylim=(0.05, 0.6))
        scat = ax.scatter([], [], color='black', alpha=0.5)

        sabr, = ax.plot([], [], lw=3, color='blue', ls='--')

        curve, = ax.plot([], [], lw=3, color='red', ls=':')

        def init():
            curve.set_data([], [])
            sabr.set_data([], [])
            scat.set_offsets(np.array([]))
            return curve, scat, sabr

        def animate(i):

            def points(trades):
                points = []
                for trade in trades:
                    points.append((float(trade.strike), float(trade.fill_iv)))
                return points

            x = np.linspace(2500, 4500, 2000)
            next_stamp = next(generator)
            x = [item for item in x]

            print(next_stamp)
            # trades = self.active_trade_chronolog[next_stamp]
            # points = points(trades)

            try:
                print('TRYING NOW')
                trades = self.active_trade_chronolog[next_stamp]
                print('trades is now {}'.format([trade.fill_iv for trade in trades]))
                print('FINISHED TRADES IS NOW')

                # trades = self.get_batch(timestamp=next_stamp)
                scatter_points = points(trades)
                print('JUST SCATTERED POINTS')
                # print('points = {}'.format(scatter_points))

                poly = self.chronolog[next_stamp]
                # print('GOT POLY')
                # print(poly)
                # print('data = {}'.format(list(poly(a) for a in x)))
                curve.set_data(x, [list(poly(a) for a in x)])
                print('JUST SET CURVE')

                model = self.sabr_log[next_stamp]
                print('GOT MODEL')
                if model is not None:
                    sabr.set_data(x, [model.volatility_from_K(val) for val in x])
                scat.set_offsets(np.array(scatter_points))

            except (KeyError, IndexError, ValueError):
                pass


            ax.set_title('{}'.format(next_stamp))
            return poly, scat, sabr

        anim = FuncAnimation(fig, animate, frames=4000, init_func=init, interval=5, blit=False)
        anim.save('{}.gif'.format(self.expiry))
        plt.show()

    def stamp_generator(self):
        for time_stamp in sorted([key for key in self.stamp_archive.timestamps.keys() if self.expiry in self.stamp_archive.timestamps[key].expirations]):
            yield time_stamp

    def get_batch(self, timestamp):
        print('getting_batch - {} - {}'.format(self.expiry, timestamp))
        batch = []
        try:
            for strike in self.stamp_archive.timestamps[timestamp].expirations[self.expiry].strikes:
                strike_obj = self.stamp_archive.timestamps[timestamp].expirations[self.expiry].strikes[strike]
                batch.extend(strike_obj.tally)
        except KeyError:
            pass

        return batch

    def check_for_newer_trade(self, trade):
        for test_trade in self.active_trades:
            # print('testing {} against {}'.format(test_trade.age, trade.age))
            if (test_trade.strike == trade.strike) and (test_trade.age < trade.age):
                # print('FOUND ONE {}/{} - ages - {}/{}'.format(trade, test_trade, trade.age, test_trade.age))
                return True
            else:
                continue
        else:
            return False


class CurveTrade:

    def __init__(self, trade: Trade, life_span):
        self.option_type = trade.option_type
        self.T = trade.T
        self.symbol = trade.underlying
        self.underlying_price = float(trade.underlying_price)
        self.strike = float(trade.strike)
        self.fill_iv = float(trade.volatility)

        self.fill_price = float(trade.trade_price)

        self.weight = life_span
        self.starting_weight = self.weight

        self.bid, self.ask = float(trade.best_bid), float(trade.best_ask)
        self.spread = self.ask - self.bid

        # clean house for bugs ~ no weights if fill_iv is 0-----

        # Filter for errant trades coming in outside of the spread.  These will be flagged using other methods.

        if self.fill_price < self.bid or self.fill_price > self.ask:
            self.fill_iv = iv_from_price(S=self.underlying_price, K=self.strike, T=self.T, option_type=self.option_type,
                                         q=0, option_price=((self.bid + self.ask)/2))

        self.time_stamp = trade.quote_datetime
        self.decay_rate = 1

        self.active_time = self.time_stamp

        self.age = 0

        self.triggered = False

        self.ghost_decay = 0

    def project_to_time(self, time_stamp: str, trigger: bool):

        now = datetime.datetime.strptime(self.active_time, '%Y-%m-%d %H:%M:%S.%f')
        future = datetime.datetime.strptime(time_stamp, '%Y-%m-%d %H:%M:%S.%f')

        diff = future - now

        self.decay(elapsed=round(diff.total_seconds()), trigger=trigger) #change trigger mechanisms back to 'trigger'
        self.set_active_time(time_stamp=time_stamp)
        self.age += diff.total_seconds()

    def decay(self, elapsed, trigger=False):
        if self.triggered is True:
            trigger = True

        if trigger is True:
            # process pent up decay
            if self.decay_rate > 0:
                self.weight -= min(self.ghost_decay, self.weight)
                self.ghost_decay = 0
            # -----------------------------------------------
            self.weight = self.weight - (self.decay_rate * elapsed)
            if self.weight < 0:
                self.weight = 0

            self.triggered = True
        else:
            self.ghost_decay += (self.decay_rate * elapsed)

    def set_active_time(self, time_stamp: str):
        self.active_time = time_stamp

    def adjust_decay_rate(self, adjustment):
        self.decay_rate = self.decay_rate + adjustment


class Modulator:

    def __init__(self, Curve: VolatilityCurve):
        self.Curve = Curve
        self.T = self.Curve.T
        self.last_stamp = None
        self.seconds_elapsed = 1
        self.iv_filter = 0.05
        self.last_model = None
        self.memory = 0

        self.multiplier = 5

        self.cut_offs = {(0.0, 0.01): 0.01,
                         (0.01, .025): 0.02,
                         (0.025, .05): 0.02,
                         (0.05, 0.075): 0.02,
                         (0.075, 0.10): 0.03,
                         (0.10, 0.125): 0.03,
                         (0.125, 0.15): 0.04,
                         (0.15, 0.20): 0.05,
                         (0.20, 0.30): 0.10,
                         (0.30, np.inf): np.inf}

        self.arrival_by_distance = {(0.0, 0.01): 0,
                                     (0.01, .025): 0,
                                     (0.025, .05): 0,
                                     (0.05, 0.075): 0,
                                     (0.075, 0.10): 0,
                                     (0.10, 0.125): 0,
                                     (0.125, 0.15): 0,
                                     (0.15, 0.20): 0,
                                    (0.20, np.inf): 0}

        self.arrival_rates_per_second = {(0.0, 0.01): 10,
                                         (0.01, .025): 10,
                                         (0.025, .05): 10,
                                         (0.05, 0.075): 10,
                                         (0.075, 0.10): 10,
                                         (0.10, 0.125): 10,
                                         (0.125, 0.15): 10,
                                         (0.15, 0.20): 10,
                                         (0.20, np.inf): 0}

        self.volume_by_segment = {(0.0, 0.01): 10,
                                 (0.01, .025): 9,
                                 (0.025, .05): 8,
                                 (0.05, 0.075): 7,
                                 (0.075, 0.10): 6,
                                 (0.10, 0.125): 5,
                                 (0.125, 0.15): 4,
                                 (0.15, 0.20): 3,
                                  (0.20, np.inf): 1}


        self.arrival_log = []

        self.strike_volatility_distributions = {}
        self.strike_volume_distribution = []



        self.atm = None
        self.atm_strike = None
        self.atm_vol = None

        self.current_kernel = None

        #NOTES FOR TOMORROW

        # LOOKIN TO USE ARR/PER SECOND TO QUANTIFY SEGMENTED ARRIVAL RATES.  NEED TO KEEP WEIGHTS AND DECAYS MOVING IN TANDEM TO KEEP A PREDICTED CURVE ON THE BOARD
        #....AND THAT MEANS POTENTIALLY EXPANDING THE LIST ABOVE TO INCLUDE MORE SPECIFIC INCREMENTS.  AFTER WE DO THIS TO DETERMINE WHAT THE NEW WEIGHTS WILL BE ON TEH INCOMING BATCH
        #....(WHICH I WILL NEED TO ADJUST THE CURVTRADE CLASS TO TAKE AS INPUTS), WE WILL NEED TO CONTEXTUALLY REWEIGHT THE ENTIRE THING TO GIVE PRECEDENT TO THE TRADES COMING IN ATM, VARYING OUT TOWARD THE WINGS SO THOSE DONT MATTER
        #....AS MUCH... SOMETHING LIKE (0.1, 0.3, 0.5, 0.7, 0.9, 1.0, 0.9,......ETC)  THIS IS AFTER WE HAVE ALREADY WEIGHTED THE TRADES BY NUMBER EXTANT AT THE STRIKE AND THEIR RELATIVE
        #....WEIGHTS AND RECENCY.  USE INFO TO UPDATE WEIGHT INPUTS AS TIME GOES FORWARD.

    def add_trades_to_strike_volatility_distribution(self, trades):
        for trade in trades:
            if trade.strike not in self.strike_volatility_distributions.keys():
                self.strike_volatility_distributions[float(trade.strike)] = [float(trade.volatility)]
            else:
                L = self.strike_volatility_distributions[float(trade.strike)]
                L.append(trade.volatility)

    def add_trades_to_strike_volume_distribution(self, trades):
        for trade in trades:
            self.strike_volume_distribution.append(float(trade.strike))

    def get_kernel(self):
        K = None
        try:
            K = si.gaussian_kde(self.strike_volume_distribution)
        except (ValueError, np.linalg.LinAlgError):
            pass
        return K

    def reset_arrival_log(self):
        self.arrival_log = []

    def log_arrival_strikes(self, trades):
        for trade in trades:
            self.arrival_log.append(trade)

    def set_atms(self):
        trade = self.arrival_log[0]
        self.atm = trade.underlying_price
        try:
            self.atm_strike, self.atm_vol = self.get_atm_vol(trades=self.updated_trades)
        except (AttributeError, IndexError):
            try:
                self.atm_strike, self.atm_vol = self.get_atm_vol(trades=self.proposed_additions)
            except IndexError:
                self.atm_strike, self.atm_vol = trade.strike, trade.volatility

    def modulate(self, current_trades, proposed_additions, new_time_stamp):

        self.current_trades, self.proposed_additions, self.new_time_stamp = current_trades, proposed_additions, new_time_stamp

        # Set the arrival Log --------------------------
        self.log_arrival_strikes(trades=self.proposed_additions)
        # ----------------------------------------------

        # Add to distributions -------------------------------------------------------------
        self.add_trades_to_strike_volatility_distribution(trades=self.proposed_additions)
        self.add_trades_to_strike_volume_distribution(trades=self.proposed_additions)
        # -----------------------------------------------------------------------------------
        self.current_kernel = self.get_kernel()
        # set and update atm values
        self.set_atms()

        # Move Trades to Present----------------------------------
        for trade in current_trades:
            # print('decaying_modulator ={}'.format(self.check_for_newer_trade(trade=trade)))
            trade.project_to_time(time_stamp=new_time_stamp, trigger=True)

        # --------------------------------------------------------'
        # Now let's Purge the fully decayed Trades------------------
        contemporary_trades = self.purge(trades=current_trades)
        # print('first set of contemporary trades = {}'.format(contemporary_trades))
        # print('CONT = {}'.format(contemporary_trades))
        #-----------------------------------------------------------

        # Adjust Internal Clock -------------------------------
        if self.last_stamp is not None:
            now = datetime.datetime.strptime(self.last_stamp, '%Y-%m-%d %H:%M:%S.%f')
            future = datetime.datetime.strptime(new_time_stamp, '%Y-%m-%d %H:%M:%S.%f')
            self.seconds_elapsed += (future - now).total_seconds()
            self.last_stamp = new_time_stamp
        else:
            self.last_stamp = new_time_stamp
        # -----------------------------------------------------

        # Now let's tally the new arrivals---------------------
        atm_value = self.atm
        for trade in proposed_additions:
            try:
                differential = abs(float(trade.strike) - atm_value) / atm_value
                for pair in sorted(self.arrival_by_distance.keys()):
                    if pair[0] < differential < pair[1]:
                        self.arrival_by_distance[pair] += 1
            except ZeroDivisionError:
                continue

        # -----------------------------------------------------

        # Calculate New Arrival Rates--------------------------
        for pair in sorted(self.arrival_by_distance.keys()):
            print('self.arrival by distance[pair] = {} ----- seconds elapsed = {} '.format(self.arrival_by_distance[pair], self.seconds_elapsed))
            self.arrival_rates_per_second[pair] = self.arrival_by_distance[pair] / self.seconds_elapsed
        # -----------------------------------------------------

        # Update_per_day_volume
        # total_volume = sum([self.arrival_by_distance[key] for key in self.arrival_by_distance.keys()])
        # percentage = 0
        # for pair in sorted(self.arrival_by_distance.keys()):
        #     percentage += (self.arrival_by_distance[pair] / total_volume )
        #     self.volume_by_segment[pair] = (1 - percentage)  # keeps running volume tabs on a per trading day basis.

        # Add in New Trades------------------------------------
        curve_trades = []
        for trade in proposed_additions:

            if abs(float(trade.trade_delta)) < 1.0 and trade.volatility != 0.0:

                differential = abs(float(trade.strike) - atm_value) / atm_value
                span = self.get_span(differential=differential)
                trade = CurveTrade(trade=trade, life_span=span)
                if trade.fill_iv != 0.0:
                    curve_trades.append(trade)
                print('JUST ADDED {}'.format(trade.fill_iv))

        # print('C = {}'.format(curve_trades))
        contemporary_trades.extend(curve_trades)
        # print('contemp trades is now {}'.format([trade.fill_iv for trade in contemporary_trades]))
        self.updated_trades = contemporary_trades
        # print('and we have set ukpdated trades to {}'.format([trade.fill_iv for trade in self.updated_trades]))

        # print('active TRADES = {}'.format(self.updated_trades))



        # print('UPDATED TRADES = {}'.format(self.updated_trades))
        # -----------------------------------------------------
        # Now let's Weigh Everything up

        self.weighed = self.method_weigh(trades=self.updated_trades)
        # self.weighed = self.standard_weigh(trades=self.updated_trades)
        # self.weighed = self.method_two_weigh(trades=self.updated_trades)

        # Let's Fit our Models ---------------------------------------------------------

        self.polynomial = self.fit_polynomial(trades=self.weighed)


        atm_vol = self.atm_vol
        print('fitting guess, atm vol = {}'.format(atm_vol))
        # sabr = self.fit_sabr(trades=self.weighed, guess=[self.atm_vol, -0.5, 0.5])
        if self.last_model is not None:
            # sabr = self.fit_sabr(trades=self.weighed, guess=[self.last_model.alpha, self.last_model.p, self.last_model.volvol])
            sabr = self.method_sabr_fit(trades=self.weighed, guess=[self.last_model.alpha, self.last_model.p, self.last_model.volvol])
        else:
            # sabr = self.fit_sabr(trades=self.weighed, guess=[self.atm_vol, -0.5, 0.5])
            sabr = self.method_sabr_fit(trades=self.weighed, guess=[self.atm_vol, -0.5, 0.5])

        if sabr is not None:
            if abs(sabr.alpha - atm_vol / atm_vol) < 0.10:
                if self.memory < 10:
                    self.last_model = sabr
                    self.memory += 1
                else:
                    self.memory = 0
                    self.last_model = None
            else:
                self.last_model = None
                self.memory = 0

        # reset arrival log---------------
        self.reset_arrival_log()

        return self.updated_trades, self.weighed, sabr, self.polynomial

    def get_span(self, differential):
        # spans = {'$SPX.X': 60,
        #          'BAC': 1000}
        max = 150 if self.Curve.underlying_symbol == '$SPX.X' else 1000
        min = 10 if self.Curve.underlying_symbol == '$SPX.X' else 120
        for pair in sorted(self.arrival_rates_per_second.keys()):
            if pair[0] < differential < pair[1]:
                span = self.arrival_rates_per_second[pair]
                span = 10 * (1/span)
                break
        else:
            span = max

        if span > max:
            span = max
        if span < min:
            span = min
        return span

    def get_atm_vol(self, trades):
        atm = self.atm
        atm_strike = sorted([trade for trade in trades], key=lambda x: abs(float(x.strike) - atm))[0].strike
        atm_vol = sorted([trade for trade in trades if float(trade.strike) == atm_strike], key=lambda x: x.age)[0].fill_iv
        return atm_strike, atm_vol

    # def method_two_weigh(self, trades):
    #     atm = self.get_atm(trades=trades)
    #     averages = self.get_strike_averages(trades=trades)
    #     weighted = self.get_volume_weights(atm=atm, averages=averages, trades=trades)
    #     return weighted

    # def get_volume_weights(self, atm, averages: dict, trades):
    #     print('AVERAGES')
    #     print(averages)
    #     atm = atm
    #     atm_strike = sorted([trade for trade in trades], key=lambda x: abs(x.strike - atm))[0].strike
    #     print('atm, atm strike = {},{}'.format(atm, atm_strike))
    #     atm_vol = sorted([trade for trade in trades if trade.strike == atm_strike], key=lambda x: x.age)[0].fill_iv
    #     print('time is {}; atm_vol = {}'.format(self.new_time_stamp, atm_vol))
    #     low_margin = .20 * atm_vol
    #     high_margin = .75 * atm_vol
    #     high = atm_vol + high_margin
    #     low = atm_vol - low_margin
    #
    #     weighted_points = []
    #     for strike in sorted(averages.keys()):
    #         print(strike)
    #         diff = abs(strike - atm) / atm
    #         print(diff)
    #         proper_segment = None
    #         for pair in sorted(self.volume_by_segment.keys()):
    #             if pair[0] <= diff <= pair[1]:
    #                 proper_segment = pair
    #                 print('found proper: {}'.format(pair))
    #         volume_weight = round(self.volume_by_segment[proper_segment] * 100)
    #         print(averages[strike], 'this is the averaged iv')
    #         if low <= averages[strike] <= high:
    #             print('passed test')
    #             pair = (strike, averages[strike])
    #             for i in range(volume_weight):
    #                 weighted_points.append(pair)
    #     # print('WEIHGTED TRADES = {}'.format(weighted_points))
    #
    #     return weighted_points

    def get_strike_averages(self, trades):
        averages = {}
        for trade in trades:
            if trade.strike in averages.keys():
                summer, total = averages[trade.strike]
                summer_new, total_new = summer + (trade.fill_iv * trade.weight), total + trade.weight
                averages[trade.strike] = (summer_new, total_new)
            else:
                averages[trade.strike] = ((trade.fill_iv * trade.weight), trade.weight)

        # print('earlier average before final average')
        # print(averages)
        final_averages = {}
        for key in averages.keys():
            pair = averages[key]
            # print('PAIR', pair)
            final_averages[key] = round(pair[0] / pair[1], 4)

        return final_averages

    def method_sabr_fit(self, trades, guess=None):
        spot = self.atm
        forward = self.Curve.forward_price(spot=spot, )
        return_type = None

        mean, std = np.mean(self.strike_volume_distribution), np.std(self.strike_volume_distribution)
        low, high = mean - (2*std), mean + (2*std)

        # low, high = spot +



        try:
            model = SABR(f=forward, t=self.Curve.T)
            model.fit_parameters(x_data=[item[0] for item in trades if low <= item[0] <= high], y_data=[self.polynomial(item[0]) for item in trades if low <= item[0] <= high], guess=guess)
            # print('JUST fit SABR model')
            # print('JUST FIT TO: {}'.format(trades))
            # print(model)
            return_type = model
        except (TypeError, RuntimeError, ValueError):
            pass

        return return_type

    def fit_sabr(self, trades, guess=None):
        # trades = self.accept_additions(trades=trades)
        spot = self.atm
        forward = self.Curve.forward_price(spot=spot, )
        return_type = None

        try:
            model = SABR(f=forward, t=self.Curve.T)
            model.fit_parameters(x_data=[item[0] for item in trades], y_data=[item[1] for item in trades], guess=guess)
            # print('JUST fit SABR model')
            # print('JUST FIT TO: {}'.format(trades))
            # print(model)
            return_type = model
        except (TypeError, RuntimeError, ValueError):
            pass

        return return_type

    def fit_polynomial(self, trades):
        atm = self.atm
        atm_vol = self.atm_vol

        low_margin = 0.75 * atm_vol
        high_margin = 1.75 * atm_vol
        high = atm_vol + high_margin
        low = atm_vol - low_margin

        # print('WEIGHING - LENGTH OF TRADES = {}'.format(len(trades)))

        x, y = [], []
        for item in trades:
            if low <= item[1] <= high:
                x.append(item[0])
                y.append(item[1])

        if len(x) == 0:
            x, y = [1], [1]

        # print('FITTING TO {}'.format([trade[1] for trade in trades]))
        P = np.polynomial.polynomial.polyfit(x, y, deg=6)
        return np.polynomial.polynomial.Polynomial(P)

    def standard_weigh(self, trades):
        atm = self.get_atm(trades=trades)
        atm_strike = sorted([trade for trade in trades], key=lambda x: abs(x.strike - atm))[0].strike
        print('atm, atm strike = {},{}'.format(atm, atm_strike))
        atm_vol = sorted([trade for trade in trades if trade.strike == atm_strike], key=lambda x: x.age)[0].fill_iv
        print('time is {}; atm_vol = {}'.format(self.new_time_stamp, atm_vol))
        low_margin = 10.20 * atm_vol
        high_margin = 10.75 * atm_vol
        high = atm_vol + high_margin
        low = atm_vol - low_margin

        multiples = []
        for trade in trades:
            if low <= trade.fill_iv <= high:
                pair = (float(trade.strike), float(trade.fill_iv))
                for i in range(int(round(trade.weight))):
                    multiples.append(pair)

        return multiples

    def method_weigh(self, trades):
        structured_strikes, volume = self.structure_weighted_strike_points(trades=trades)
        weighted_by_volume = self._weigh_by_volume(structured_strikes=structured_strikes, trades=trades, volume=volume)
        return weighted_by_volume


    def _weigh_by_volume(self, structured_strikes: dict, trades, volume: dict):
        # atm = self.get_atm(trades=trades)
        atm = self.atm
        # atm_strike = sorted([trade for trade in trades], key=lambda x: abs(x.strike - atm))[0].strike
        atm_strike = self.atm_strike
        print('atm, atm strike = {},{}'.format(atm, atm_strike))
        # atm_vol = sorted([trade for trade in trades if trade.strike == atm_strike], key=lambda x: x.age)[0].fill_iv
        atm_vol = self.atm_vol
        print('time is {}; atm_vol = {}'.format(self.new_time_stamp, atm_vol))

        low_margin = 0.75 * atm_vol
        high_margin = 1.75 * atm_vol
        high = atm_vol + high_margin
        low = atm_vol - low_margin


        volume_multiplier = 0
        weighted_by_volume = []
        # atm = self.get_atm(trades=trades)
        for strike in structured_strikes.keys():
            volume_multiplier = volume[strike]
            # try:
            #     mean, std = np.mean(self.strike_volatility_distributions[strike]), np.std(self.strike_volatility_distributions[strike])
            #     low, high = mean - (2*std), mean + (2*std)
            # except KeyError:
            #     low, high = 0, 10000

            if low <= structured_strikes[strike] <= high:
                pair = (strike, structured_strikes[strike])
                for i in range(volume_multiplier):
                    weighted_by_volume.append(pair)
        return weighted_by_volume

    # def _weigh_by_volume(self, structured_strikes: dict, trades, volume: dict):
    #     # atm = self.get_atm(trades=trades)
    #     atm = self.atm
    #     # atm_strike = sorted([trade for trade in trades], key=lambda x: abs(x.strike - atm))[0].strike
    #     atm_strike = self.atm_strike
    #     print('atm, atm strike = {},{}'.format(atm, atm_strike))
    #     # atm_vol = sorted([trade for trade in trades if trade.strike == atm_strike], key=lambda x: x.age)[0].fill_iv
    #     atm_vol = self.atm_vol
    #     print('time is {}; atm_vol = {}'.format(self.new_time_stamp, atm_vol))
    #
    #
    #
    #
        # low_margin = 0.75 * atm_vol
        # high_margin = 1.75 * atm_vol
        # high = atm_vol + high_margin
        # low = atm_vol - low_margin
    #
    #     volume_multiplier = 0
    #     weighted_by_volume = []
    #     # atm = self.get_atm(trades=trades)
    #     for strike in structured_strikes.keys():
    #         if self.current_kernel is not None:
    #             volume_multiplier = (self.current_kernel.evaluate(strike)[0] )
    #             print('just set by PDF')
    #             print('volume mult = {}'.format(volume_multiplier))
    #         else:
    #             volume_multiplier = volume[strike]
    #
    #         try:
    #             mean, std = np.mean(self.strike_volatility_distributions[strike]), np.std(self.strike_volatility_distributions[strike])
    #             low, high = mean - (2*std), mean + (2*std)
    #         except KeyError:
    #             low, high = 0, 10000
    #
    #         if low <= structured_strikes[strike] <= high:
    #             pair = (strike, structured_strikes[strike])
    #             try:
    #                 for i in range(volume_multiplier):
    #                     weighted_by_volume.append(pair)
    #             except TypeError:
    #                 print('MULT ERROR = {}'.format(volume_multiplier))
    #
    #
    #     return weighted_by_volume

    @staticmethod
    def purge(trades):
        return_trades = []
        for trade in trades:
            if trade.weight > 0:
                return_trades.append(trade)
        return return_trades

    @staticmethod
    def snag_most_recent_trades(trades):
        try:
            sorted(trades, key=lambda x: x.age)[0]
        except AttributeError:
            return trades[0]


        return sorted(trades, key=lambda x: x.age)[0]

    def trigger_by_proximity(self, trade, trades):
        return_bool = False
        atm_value = self.get_atm(trades=trades)
        differential = abs(trade.strike - atm_value) / atm_value

        trigger_distance = 0.000
        for pair in sorted(self.cut_offs.keys()):
            if pair[0] <= differential <= pair[1]:
                trigger_distance = self.cut_offs[pair]
                break
            else:
                continue
        else:
            return_bool = True

        for test_trade in sorted([t_trade for t_trade in trades], key=lambda x: abs(x.strike - trade.strike)):
            if not abs(test_trade.strike - trade.strike) / trade.strike <= trigger_distance:
                return_bool = False
                break
            if abs(test_trade.strike - trade.strike) / trade.strike <= trigger_distance and test_trade.age < trade.age:
                return_bool = True
                break


        return return_bool

    def get_atm(self, trades):
        return self.snag_most_recent_trades(trades=trades).underlying_price

    def structure_weighted_strike_points(self, trades):
        Averaged_Strike_Vols = self.get_strike_averages(trades=trades)
        strike_volume = dict()
        Strike_vols = dict()
        for trade in trades:
            if trade.strike in Strike_vols.keys():
                # log = Strike_vols[trade.strike]
                # for i in range(int(round(trade.weight))):
                #     log.append(trade.fill_iv)
                strike_volume[trade.strike] += 1
            else:
                # print(trade.weight)
                # Strike_vols[trade.strike] = [trade.fill_iv for i in range(int(round(trade.weight)))]
                strike_volume[trade.strike] = 1

        # Averaged_Strike_Vols = dict()
        # for key in Strike_vols:
        #     av = np.mean(Strike_vols[key])
        #     Averaged_Strike_Vols[key] = av

        return Averaged_Strike_Vols, strike_volume

    def check_for_newer_trade(self, trade):
        # print('testing mod decay, here is the arrival log: {}'.format([t.strike for t in self.arrival_log]))
        # print('and here is the trade strike = {}'.format(trade.strike))
        if trade.triggered is False:
            if trade.strike in [float(t.strike) for t in self.arrival_log]:
                return True
            else:
                return False
        else:
            return True

    def __str__(self):
        print('-' * 50)
        print('AS OF {}'.format(self.last_stamp))
        print('-' * 10)
        print('{} seconds elapsed'.format(self.seconds_elapsed) )
        print('-' * 25)
        print('-' * 25)
        print(self.arrival_by_distance)
        print('-' * 25)
        print(self.arrival_rates_per_second)
        print('-' * 25)
        print(self.volume_by_segment)
        print('-' * 50)
        return ''

    def accept_additions(self, trades):
        passed = []
        self.update_t()

        for trade in trades:
            # print(trade)
            # if trade.volatility < 0.025:
            #     print('WTF!!')
            predicted_price = BlackSholesMerton(S=trade.underlying_price, K=float(trade.strike), r=risk_free_rate,
                                                q=dividends[trade.underlying], T=self.T, sigma=trade.volatility,
                                                option_type=trade.option_type)
            if (float(trade.best_bid) <= predicted_price.Premium <= float(trade.best_ask)):
                # print('ok here it is, lmao: {} to {}'.format(trade.trade_delta, abs(float(trade.trade_delta))))
                if abs(float(trade.trade_delta)) < 1.0:
                    passed.append(trade)
                    # print('just appended {}({}), bid = {}, ask = {}, trade_delta = {}'.format(trade.volatility, predicted_price.Premium, trade.best_bid, trade.best_ask, trade.trade_delta))
            else:
                pass
                # print('failed test, trade delta = {}'.format(trade.trade_delta))
        return passed

    def update_t(self):
        now = datetime.datetime.strptime(self.new_time_stamp, '%Y-%m-%d %H:%M:%S.%f')
        future = datetime.datetime.strptime('{} 16:00:00.000'.format(self.Curve.expiry), '%Y-%m-%d %H:%M:%S.%f')

        diff = future - now

        self.T = diff.total_seconds() / (365 * 24 * 60 * 60)









































