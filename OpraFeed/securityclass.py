import requests
import datetime
import numpy as np
import scipy.stats as si
from BlackSholesMerton.Black_Sholes_Merton import BlackSholesMerton, risk_free_rate, dividends, iv_from_price


class Security:

    def __init__(self, symbol):
        self.symbol = symbol
        self.data_pack = self.request_td_opchain()
        self.price = self.data_pack['underlying']['mark']
        self.putmap = self.data_pack['putExpDateMap']
        self.callmap = self.data_pack['callExpDateMap']
        self.expirations = self.instantiate_contracts()
        self.gex = round(self.gamma_exposure())
        self.dollar_gamma = round(self.gex * self.price, 2)

    def __str__(self):
        string = '{0.symbol:8}|${0.price:10}|{0.gex:10}|${0.dollar_gamma:15}'.format(self)
        return string

    def request_td_opchain(self):
        symbol = self.symbol
        endpoint = 'https://api.tdameritrade.com/v1/marketdata/chains'
        accesskey = 'RJGZGRIGBKYCFJEYJBI6LPFSY6OGPCYF'
        payload = {'apikey': accesskey,
                   'symbol': '{}'.format(symbol),
                   'contractType': 'ALL',
                   'includeQuotes': 'TRUE',
                   'strategy': 'SINGLE',
                   'range': 'ALL'
                   }
        content = requests.get(url=endpoint, params=payload)
        print(content)
        data = content.json()
        return data

    def instantiate_contracts(self):
        expirations = {}
        for date in self.callmap:
            obj = Contract(security=self, date=date)
            expirations[obj.date[0:10]] = obj
        return expirations

    def gamma_exposure(self):
        gamma = 0
        for contract in self.expirations:
            gamma += self.expirations[contract].gex
        return gamma

    def custom_gamma(self, distance):
        gamma = 0
        for contract in self.expirations:
            if int(self.expirations[contract].days_to_expiration) <= distance:
                contractobject = self.expirations[contract]
                for strike in contractobject.calls:
                    strikeobject = contractobject.calls[strike]
                    gamma += strikeobject.gex
                for strike in contractobject.puts:
                    strikeobject = contractobject.puts[strike]
                    gamma += strikeobject.gex
        dollargamma = gamma * self.price
        return gamma, dollargamma

    def print_check(self, date):
        raw = self.data_pack
        call_date_map = raw['putExpDateMap']
        for item in call_date_map:
            print(item)
            print(call_date_map[item])
            for thing in call_date_map[item]:
                print(thing, call_date_map[item][thing][0]['gamma'], call_date_map[item][thing][0]['openInterest'])
                date = item[0:10]
                strikeobj = self.expirations[date].puts[thing]
                print('From Program', strikeobj.strike_price, strikeobj.gamma, strikeobj.openInterest, strikeobj.gex)
        calls_total = 0
        for strike in self.expirations[date].calls:
            calls_total += self.expirations[date].calls[strike].gex
            print('new total = {}'.format(calls_total))
        print('-' * 50)
        for strike in self.expirations[date].puts:
            calls_total += self.expirations[date].puts[strike].gex
            print('new total = {}'.format(calls_total))


class Contract:

    def __init__(self, security, date):
        self.date = date
        self.days_to_expiration = self.trading_days_conversion(calendar_days=int(self.date[11::]))
        self.calls, self.puts = self.instantiate_strikes(security=security, date=date)
        self.gex = self.expiration_gamma()



    def instantiate_strikes(self, security, date):
        calls, puts = {}, {}
        for strike in security.callmap[date]:
            obj = Strike(security.callmap[date], strike, days=self.days_to_expiration, underlying_price=security.price, underlying_symbol=security.symbol)
            calls[obj.strike_price] = obj
        for strike in security.putmap[date]:
            obj = Strike(security.putmap[date], strike, days=self.days_to_expiration, underlying_price=security.price, underlying_symbol=security.symbol)
            puts[obj.strike_price] = obj
        return calls, puts

    def expiration_gamma(self):
        gamma = 0
        for strike in self.calls:
            if type(self.calls[strike].gex) is not str:
                gamma += self.calls[strike].gex
        for strike in self.puts:
            if type(self.puts[strike].gex) is not str:
                gamma += self.puts[strike].gex
        return gamma

    @staticmethod
    def trading_days_conversion(calendar_days):
        today = datetime.datetime.now().weekday()
        days = calendar_days

        to_subtract = 0
        count = today
        for i in range(calendar_days):
            count += 1
            if count == 7:
                count = 0
            if count in (5, 6):
                to_subtract += 1
        days -= to_subtract

        return days


class Strike:

    def __init__(self, dictionary, price, days, underlying_price, underlying_symbol):
        self.underlying_price = underlying_price
        self.days_until_expiration = days
        self.contract = dictionary[price][0]

        self.bid = self.contract['bid']
        self.ask = self.contract['ask']
        self.midpoint = (self.bid + self.ask) / 2

        # self.price = dictionary['markPrice']
        self.type = self.contract['putCall']
        self.strike_price = price
        self.symbol = self.contract['symbol']
        self.iv = self.contract['volatility']

        self.volume = self.contract['totalVolume']
        self.delta = self.contract['delta']
        self.gamma = self.contract['gamma']
        self.vega = self.contract['vega']
        self.openInterest = self.contract['openInterest']
        self.gex = 100 * self.gamma * self.openInterest

        if self.iv == 'NaN':
            self.iv = iv_from_price(S=float(underlying_price), K=float(self.strike_price), option_price=self.midpoint,
                                    r=risk_free_rate, T=self.days_until_expiration/365, q=dividends[underlying_symbol],
                                    option_type=self.type)
        if self.gamma == 'NaN' or abs(int(self.gamma)) == 999:
            self.gamma = 0.000
        if self.delta == 'NaN' or abs(int(self.delta)) == 999:
            self.delta = 0.000
        if self.vega == 'NaN' or abs(int(self.vega)) == 999:
            self.vega = 0.000


        model = BlackSholesMerton(S=float(underlying_price), K=float(self.strike_price), r=risk_free_rate,
                                  T=self.days_until_expiration/365, q=dividends[underlying_symbol],
                                  option_type=self.type, sigma=float(self.iv)/100)
        self.vanna = model.DdelV

        # print(self.vanna)
        if np.isnan(self.vanna):
            # print('this is flagged')
            self.vanna = 0
            # print('changed vanna to {}'.format(self.vanna))






        if self.type == 'PUT':
            if type(self.gex) is not str:
                self.gex = -self.gex



#
# print(Security('TSLA'))