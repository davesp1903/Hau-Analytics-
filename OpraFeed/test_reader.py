from OpraFeed.OpraFeeds import OpraFeed
from OpraFeed.flaggers import cross_the_spread, cross_spread_bid_ask_liquidity
import matplotlib.pyplot as plt
import sqlite3




#
# # paths = {'/Users/dmith/Desktop/Hau Vol/BAC/April': 'BAC April', '/Users/dmith/Desktop/Hau Vol/BAC/February': 'BAC February',
# #          '/Users/dmith/Desktop/Hau Vol/BAC/January': 'BAC January', '/Users/dmith/Desktop/Hau Vol/BAC/March': 'BAC March'}
#
#
#
# feb_5 = '/Users/dmith/Desktop/Feb-5th BAC trades'
# feed = OpraFeed(folder=feb_5, flagger_function=cross_spread_bid_ask_liquidity, binning_method='deviation')
#
# tracker = feed.get_liquidity_tracker()
# fig = tracker.plot_nanex_style()
# plt.show()
# # tracker.to_gui()
#
#
# db = sqlite3.connect('EQUITY_TRADE_DATA.sqlite')
# db.execute("""CREATE TABLE IF NOT EXISTS securities (security_id PRIMARY KEY NOT NULL, symbol TEXT, unique(symbol))""")
# db.execute("""CREATE TABLE IF NOT EXISTS dates (date_id PRIMARY KEY NOT NULL, date TEXT, unique(date))""")
# db.execute("""CREATE TABLE IF NOT EXISTS histories (id PRIMARY KEY NOT NULL, security_id INT, date_id INT, delta INT, gamma INT,
#  vega INT, vanna INT, callsBought, callsSold, PutsBought, PutsSold, sequence INT, unique(security_id, date_id))""")
#
# db.execute("""CREATE TABLE IF NOT EXISTS EODStats (id PRIMARY KEY NOT NULL, security_id INT, date_id INT,
#  expiration_date TEXT, strike TEXT, callput TEXT, DDOI INT, delta INT, gamma INT, vega INT, vanna INT, unique(security_id, expiration_date, strike, callput) )""")
#
# db.execute("""INSERT INTO securities VALUES(1, 'BAC')""")
#
#
# db.commit()
# db.close()


# db = sqlite3.connect('HAU_TRADE_DATABASE.sqlite')
# db.execute("PRAGMA foreign_keys = ON")
# db.execute('CREATE TABLE IF NOT EXISTS Trades (id PRIMARY KEY NOT NULL,'
#            ' underlying_symbol TEXT, quote_datetime, sequence_number INT, root TEXT, expiration TEXT, strike INT, option_type TEXT,'
#            ' trade_size INT, trade_price FLOAT, trade_condition_id INT, canceled_trade_condition_id INT, best_bid FLOAT,'
#            'best_ask FLOAT, underlying_bid FLOAT, underying_ask FLOAT, number_of_exchanges INT, delta FLOAT, gamma FLOAT, vega FLOAT, vanna FLOAT)')
# db.execute('CREATE TABLE IF NOT EXISTS Exchanges (id PRIMARY KEY NOT NULL, trade_table_id INT, exchange_id INT, bid_size INT, bid FLOAT,'
#            ' ask_size INT, ask FLOAT, FOREIGN KEY(trade_table_id) REFERENCES Trades(id))')

