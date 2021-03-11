import sqlite3
import matplotlib.pyplot as plt
import seaborn as sns
import datetime
import matplotlib.dates as dates
import os
from OpraFeed.OpraFeeds import OpraFeed
from OpraFeed.flaggers import cross_spread_bid_ask_liquidity





class GamaByStrike:

    def __init__(self, symbol, axis, expiry_block=True, labels=True, margin=0.15):
        self.symbol = symbol
        self.strikes = {}
        self.exp_strikes = {}

        sql = "SELECT expiration, strike, dealer_directional_open_interest, gamma from DDOI where underlying_symbol = ? and isCurrent = 1 and strike > ? and strike < ? "
        db = sqlite3.connect('/Users/davesmith/Desktop/Hau DataCenter/HAU_TRADE_DATABASE.sqlite')
        self.cursor = db.cursor()

        if expiry_block is True:
            self.nearest_expiry = self.get_nearest_expiry()

        underlying_sql = 'SELECT underlying_price FROM EOD where underlying_symbol = ? and isCurrent = 1'
        self.underlying_price = self.cursor.execute(underlying_sql, (symbol,)).fetchone()[0]


        lower, upper = self.underlying_price - (self.underlying_price * margin), self.underlying_price + (self.underlying_price * margin)

        self.cursor.execute(sql, (symbol, lower, upper))
        self.calculate_and_distribute(expiry_block=expiry_block)

        x, y = [], []

        exx, exy, bottoms = [], [], []

        for key in sorted(self.strikes.keys(), key=lambda x: (float(x) * 100)):

            x.append(key)
            y.append(self.strikes[key])

            if expiry_block is True:
                for key in sorted(self.exp_strikes.keys()):
                    exx.append(key)
                    exy.append(self.exp_strikes[key])
                    # if self.exp_strikes[key] > 0:
                    #     bottoms.append(self.strikes[key])
                    # else:
                    #     bottoms.append(0)

        axis.bar(x, y, color='#99ccff', edgecolor='black', alpha=0.90, )
        if expiry_block is True:
            axis.bar(exx, exy, color='red', edgecolor='black', alpha=0.90, label='Expiring {}'.format(self.nearest_expiry))
            axis.legend()
        axis.tick_params(axis='x', rotation=45, labelsize = 'small')

        if labels is True:
            axis.set_title('Dealer Notional Exposure by Strike: {}'.format(symbol))
            axis.set_ylabel('Notional Exposure')
            axis.set_xlabel('Strike Price')


        axis.grid(axis='y', color='black', alpha=0.2, ls='--')

    def calculate_and_distribute(self, expiry_block):
        if expiry_block is True:
            print('NOT NONE')
            print(expiry_block)

            for item in self.cursor:
                print(item[0], self.nearest_expiry)
                if item[0] == self.nearest_expiry:
                    try:
                        self.exp_strikes[str(item[1])] += item[2] * item[3] * 100 * self.underlying_price
                    except KeyError:
                        self.exp_strikes[str(item[1])] = item[2] * item[3] * 100 * self.underlying_price
                    try:
                        self.strikes[str(item[1])] += item[2] * item[3] * 100 * self.underlying_price
                    except KeyError:
                        self.strikes[str(item[1])] = item[2] * item[3] * 100 * self.underlying_price

                else:

                    try:
                        self.strikes[str(item[1])] += item[2] * item[3] * 100 * self.underlying_price
                    except KeyError:
                        self.strikes[str(item[1])] = item[2] * item[3] * 100 * self.underlying_price
        else:
            for item in self.cursor:
                try:
                    self.strikes[str(item[1])] += item[2] * item[3] * 100 * self.underlying_price
                except KeyError:
                    self.strikes[str(item[1])] = item[2] * item[3] * 100 * self.underlying_price

    def get_nearest_expiry(self):
        sql = 'SELECT expiration FROM DDOI WHERE isCurrent = 1 and underlying_symbol = ? ORDER BY expiration'
        self.cursor.execute(sql, (self.symbol,))
        expiration = self.cursor.fetchone()[0]
        return expiration


    def show(self):
        plt.show()


class DeltaGraph:

    def __init__(self, symbol, axis, date=None, labels=True):

        if symbol == '$SPX.X':
            symbol = '^SPX'


        print('symbol = {}, axis = {}, date={}, labels={}'.format(symbol, axis, date, labels))
        if date is None:
            print('date is none')
            today = datetime.datetime.now()
            string = datetime.datetime.strftime(today, '%Y-%m-%m')
            string = '{} 09:00:00.000'.format(string)
        else:
            string = '{} 09:00:00.000'.format(date)
            # string = date
            print(string)

        upx, upy = [], []
        x, y = [], []
        db = sqlite3.connect('/Users/davesmith/Desktop/Hau DataCenter/HAU_TRADE_DATABASE.sqlite')
        self.cursor = db.cursor()
        sql = """SELECT quote_datetime, delta, underlying_bid, underying_ask FROM Trades WHERE underlying_symbol = ? and quote_datetime > ? and abs(delta) > 1000 ORDER by quote_datetime"""
        self.cursor.execute(sql, (symbol, string))
        for item in self.cursor:
            print(item)
            x.append(item[0])
            upx.append(item[0])
            upy.append((item[2] + item[3]) / 2)
            y.append(item[1])
        x = list(map(lambda x: dates.date2num(datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f')), x))
        upx = list(map(lambda x: dates.date2num(datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f')), upx))

        print('is the problem here?')
        print(x, upx,)

        tx = axis.twinx()
        tx.plot(upx, upy, color='blue')

        axis.scatter(x, y, color='white', edgecolor='black')
        axis.xaxis.set_major_formatter(dates.DateFormatter('%H:%M'))

        if labels is True:
            tx.set_ylabel('{} Price'.format(symbol))
            axis.set_title('TRADE DELTAS  {} - {}'.format(symbol, string[:10]))
            axis.set_ylabel('Trade Delta (Size * 100 * Delta)')
            axis.set_xlabel('Time')

        axis.grid(axis='y', color='black', alpha=0.2, ls='--')


    def show(self):
        plt.show()


class TradeVega:

    def __init__(self, symbol, axis, date=None, labels=True):
        if symbol == '$SPX.X':
            symbol = '^SPX'
        if date is None:
            today = datetime.datetime.now()
            string = datetime.datetime.strftime(today, '%Y-%m-%m')
            string = '{} 09:00:00.000'.format(string)
        else:
            string = '{} 09:00:00.000'.format(date)


        upx, upy = [], []
        x, y = [], []
        db = sqlite3.connect('/Users/davesmith/Desktop/Hau DataCenter/HAU_TRADE_DATABASE.sqlite')
        self.cursor = db.cursor()
        sql = """SELECT quote_datetime, vega, underlying_bid, underying_ask FROM Trades WHERE underlying_symbol = ? and quote_datetime > ? and abs(vega) > 100 ORDER by quote_datetime"""
        self.cursor.execute(sql, (symbol, string))
        for item in self.cursor:
            # print(item)
            x.append(item[0])
            upx.append(item[0])
            upy.append((item[2] + item[3]) / 2)
            y.append(item[1])
        x = list(map(lambda x: dates.date2num(datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f')), x))
        upx = list(map(lambda x: dates.date2num(datetime.datetime.strptime(x, '%Y-%m-%d %H:%M:%S.%f')), upx))

        tx = axis.twinx()
        tx.plot(upx, upy, color='blue')

        axis.scatter(x, y, color='white', edgecolor='black')
        axis.xaxis.set_major_formatter(dates.DateFormatter('%H:%M'))

        if labels is True:
            tx.set_ylabel('{} Price'.format(symbol))
            axis.set_title('TRADE Vegas  {} - {}'.format(symbol, string[:10]))
            axis.set_ylabel('Trade Vega (Size * 100 * Vega)')
            axis.set_xlabel('Time')

        axis.grid(axis='y', color='black', alpha=0.2, ls='--')





class GexLine:

    def __init__(self, symbol, axis):

        x, y = [], []
        db = sqlite3.connect('/Users/davesmith/Desktop/Hau DataCenter/HAU_TRADE_DATABASE.sqlite')
        self.cursor = db.cursor()
        sql = """SELECT quote_datetime, dealer_gamma_notional FROM EOD WHERE underlying_symbol = ?   ORDER by quote_datetime"""
        self.cursor.execute(sql, (symbol,))
        mem = self.cursor.fetchmany(-10)
        for item in mem:
            # print(item)
            x.append(item[0])
            y.append(item[1])

        x = list(map(lambda x: dates.date2num(datetime.datetime.strptime(x, '%Y-%m-%d')), x))
        axis.plot(x, y, color='blue', lw=1.5, marker='o', markerfacecolor='white', markeredgecolor='blue', fillstyle='full')
        axis.grid(axis='y', color='black', alpha=0.2, ls='--')


        axis.xaxis.set_major_formatter(dates.DateFormatter('%m-%d'))

    def show(self):
        plt.show()


class BuySellLine:

    def __init__(self, symbol, axis, mode=1, labels=True):

        """Modes : 1 - 3 CALLS (ITM, ATM, OTM), 4-6 PUTS, (ITM, ATM, OTM)"""

        modes = {1: ('itm_calls_bought', 'itm_calls_sold'), 2: ('atm_calls_bought', 'atm_calls_sold'),
                 3: ('otm_calls_bought', 'otm_calls_sold'), 4: ('itm_puts_bought', 'itm_puts_sold'),
                 5: ('atm_puts_bought', 'atm_puts_sold'), 6: ('otm_puts_bought', 'otm_puts_sold')}

        db = sqlite3.connect('/Users/davesmith/Desktop/Hau DataCenter/HAU_TRADE_DATABASE.sqlite')
        cursor = db.cursor()

        sql = 'SELECT quote_datetime, {}, {} FROM EOD WHERE underlying_symbol = ? ORDER by quote_datetime'.format(modes[mode][0], modes[mode][1])
        cursor.execute(sql, (symbol,))

        mem = [item for item in cursor]

        BOUGHT, SOLD = [], []

        for item in mem:
            BOUGHT.append((item[0], item[1]))
            SOLD.append((item[0], item[2]))

        ax = axis

        lines = [BOUGHT, SOLD]

        for line in lines:
            x = [point[0] for point in line]
            x = list(map(lambda y: dates.date2num(datetime.datetime.strptime(y, '%Y-%m-%d')), x))
            y = [point[1] for point in line]
            ax.plot(x, y, color='green' if line == BOUGHT else 'red',
                    label='% {} {} BOUGHT '.format(modes[mode][0].split('_')[0].upper(), modes[mode][0].split('_')[1].upper()) if line == BOUGHT else '% {} {} SOLD'.format(modes[mode][0].split('_')[0].upper(), modes[mode][0].split('_')[1].upper()), lw=3, marker='^',
                    markerfacecolor='black')
        ax.grid(axis='both', color='black', alpha=0.5, ls='--')
        ax.legend(loc='upper left')
        ax.xaxis.set_major_formatter(dates.DateFormatter('%m-%d'))

        if labels is True:
            ax.set_title('BAC PUTS - ATM Strike')

            ax.set_ylabel('Percentage of Total Volume')


    def show(self):
        plt.show()



if __name__ == '__main__':
    stocks = ['AAPL', 'TSLA', 'BAC', 'MSFT', 'FB']
    os.mkdir('SampleGraphs')
    os.chdir("SampleGraphs")

    for stock in stocks:
        vfig, vax = plt.subplots(figsize=(15,9))
        dfig, daxis = plt.subplots(figsize=(15, 9))
        fig, ax = plt.subplots(figsize=(15, 9))
        fig.patch.set_facecolor('#d6d6d6')
        fig2, ax2 = plt.subplots()

        vega = TradeVega(stock, axis=vax, date='2020-07-10 00:00:00.000')
        vfig.savefig('{}_vega.png'.format(stock), bbox_inches='tight')

        delta = DeltaGraph(stock, axis=daxis, date='2020-07-10 00:00:00.000')
        dfig.savefig('{}_delta.png'.format(stock), bbox_inches='tight')
        line = GexLine(stock, axis=ax2)
        fig2.savefig('{}_gex.png'.format(stock), bbox_inches='tight')
        graph = GamaByStrike(stock, axis=ax, expiry_block=None)

        fig.savefig('{}_gxstrike.png'.format(stock), bbox_inches='tight')



