from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from PDF.graphs_for_pdf import DeltaGraph, TradeVega, GexLine, GamaByStrike, BuySellLine
from OpraFeed.OpraFeeds import Liquidity
from OpraFeed.securityclass import Security
import shelve

import matplotlib.pyplot as plt
import os
import shutil
import sqlite3
import numpy as np


stock_info = {'FB': 'FaceBook, Inc', 'MSFT': 'Microsoft Corporation', "AAPL": 'Apple, Inc.',
              'BAC': 'Bank of America Corporation', 'TSLA': 'Tesla Motors', 'QQQ': 'Invesco QQQ Trust', '^SPX': "S&P 500 Index",
              '$SPX.X': "S&P 500 Index", 'GLD': 'SPDR Gold Trust'}
strike_margins = {'FB': 0.15, 'MSFT': 0.15, "AAPL": 0.08,
              'BAC': 0.25, 'TSLA': 0.07, 'QQQ': 0.05, '$SPX.X': 0.03, 'GLD': 0.08}

def commify(string):
    string = str(string)
    try:
        dollars, cents = string.split('.')
    except ValueError:
        dollars, cents = string, '00'
    new_string = ''
    for character in reversed(dollars):
        new_string += character
        test_string = ''
        for char in new_string:
            if char != ',':
                test_string += char
        if len(test_string) % 3 == 0:
            new_string += ','
    returnable = ''
    for char in reversed(new_string):
        returnable += char
    returnable = returnable + '.' + cents
    if returnable[0] == ',':
        returnable = returnable[1::]
    elif returnable[0] == '-':
        if returnable[1] == ',':
            returnable = returnable[0] + returnable[2::]
        else:
            returnable = returnable[0] + returnable[1::]

    return '$' + returnable



class PDF:

    def __init__(self, symbol, date, strike_margin=0.15, ltracker=None):


        self.ltracker = ltracker

        self.months_abbr = {'01': 'JAN', '02': 'FEB', '03': 'MAR', '04': 'APR', '05': 'MAY', '06': 'JUN', '07': 'JUL',
                       '08': 'AUG', '09': 'SEP', '10': 'OCT', '11': 'NOV', '12': 'DEC'}
        self.symbol = symbol


        self.date = date + ' 00:00:00.000'
        self.margin = strike_margin

        self.canvas = canvas.Canvas('{}_{}.pdf'.format(self.symbol, self.date[:10]))
        self.canvas.setPageSize(landscape(letter))

        self.canvas.drawImage('/Users/davesmith/Desktop/Hau DataCenter/PDF/Zoomed.png', 750, 575, height=30, width=30)

        self.canvas.setFont('Helvetica-Bold', 16,)
        self.canvas.drawCentredString(130, 575, 'HAU DAILY OPTIONS REPORT  {}'.format(self.date.split(' ')[0]))
        self.canvas.setFont('Helvetica', 14)

        self.canvas.drawString(80, 553.5, 'TRADE DELTAS')
        self.canvas.drawString(80, 357.5, 'TRADE VEGAS')

        self.canvas.line(x1=0, x2=795, y1=570, y2=570)

        self._plot_graphs()
        self.canvas.drawCentredString(518.75, 553.5, 'GAMMA EXPOSURE BY STRIKE PRICE')

        self.plot_sum_stats()

        self.canvas.line(x1=260, y1=570, y2=0, x2=260)
        self.canvas.line(x1=260, y1=175, y2=175, x2=795)
        self.canvas.line(x1=0, x2=260, y1=375, y2=375)
        self.canvas.line(x1=0, x2=260, y1=175, y2=175)

        # HOUSEKEEPING--------------------------------
        self.canvas.setFillColor('black')
        self.canvas.rect(x=0, y=610, width=800, height=3, fill=1)
        self.canvas.rect(x=0, y=0, width=800, height=2, fill=1)

        self.canvas.rect(x=0, y=0, width=5, height=615, fill=1)
        self.canvas.rect(x=787, y=0, width=5, height=615, fill=1)
        # HOUSEKEEPING---------------------------------------------

        self.canvas.line(x1=0, x2=800, y1=611, y2=611)

        self.canvas.showPage()


        self._second_page_graphs()
        self.highestcalls, self.highestputs = self._second_page_data()

        # HOUSEKEEPING--------------------------------
        self.canvas.setFillColor('black')
        self.canvas.rect(x=0, y=610, width=800, height=3, fill=1)
        self.canvas.rect(x=0, y=0, width=800, height=2, fill=1)

        self.canvas.rect(x=0, y=0, width=5, height=615, fill=1)
        self.canvas.rect(x=787, y=0, width=5, height=615, fill=1)
        # HOUSEKEEPING---------------------------------------------

        self.canvas.showPage()

        self.plot_color_pages()


        self.canvas.save()


    def _plot_graphs(self):
        dfig, daxis = plt.subplots(figsize=(6, 4))
        vfig, vax = plt.subplots(figsize=(6, 4))
        lfig, laxis = plt.subplots(figsize=(13.5, 3.35))
        sfig, saxis = plt.subplots(figsize=(11, 7.5))
        DeltaGraph(self.symbol, axis=daxis, date=self.date, labels=False)

        TradeVega(self.symbol, axis=vax, date=self.date, labels=False)
        GexLine(self.symbol, axis=laxis)
        GamaByStrike(self.symbol, axis=saxis, labels=False, margin=self.margin)

        current = os.getcwd()
        os.mkdir('graphs')
        os.chdir('graphs')
        plot_dir = os.getcwd()
        dfig.savefig('delta.png', bbox_inches='tight')
        vfig.savefig('vega.png', bbox_inches='tight')
        lfig.savefig('line.png', bbox_inches='tight')
        sfig.savefig('strike.png', bbox_inches='tight')
        os.chdir(current)

        self.canvas.drawImage(image=plot_dir+'/strike.png', x=262.5, y=180, width=512.5, height=375)
        self.canvas.drawImage(image=plot_dir + '/line.png', x=262.5, y=0, width=512.5, height=155)
        self.canvas.drawImage(image=plot_dir + '/delta.png', x=2, y=375, width=260, height=175)
        self.canvas.drawImage(image=plot_dir + '/vega.png', x=2, y=175, width=260, height=175)




        shutil.rmtree('graphs')

    def plot_sum_stats(self):
        db = sqlite3.connect('/Users/davesmith/Desktop/Hau DataCenter/HAU_TRADE_DATABASE.sqlite')
        cursor = db.cursor()
        sql = 'SELECT dealer_delta_notional, dealer_gamma_notional, dealer_vanna_notional, vega_notional,' \
              ' itm_calls_bought, atm_calls_bought, otm_calls_bought, itm_puts_bought, atm_puts_bought, otm_puts_bought,' \
              ' itm_calls_sold, atm_calls_sold, otm_calls_sold, itm_puts_sold, atm_puts_sold,' \
              ' otm_puts_sold, underlying_price FROM EOD WHERE underlying_symbol = ? ORDER by quote_datetime DESC'

        cursor.execute(sql, (self.symbol,))

        last5 = cursor.fetchmany(5)
        data = last5[0]
        print('DATA = {}'.format(last5[0]))


        arrays = []
        for row in last5:
            arrays.append(np.array(row[4:-1]))
        averages = arrays[0].copy()
        for item in arrays[1::]:
            averages += item
        averages = averages / 5
        print(arrays)
        print('averages = {}'.format(averages))

        self.canvas.setFont('Helvetica', 11)
        gex = commify(str(round(data[1])))
        shares = data[1]/data[-1]


        self.canvas.drawString(280, 160, ' Notional Gamma Exposure PP: {}'.format(gex))
        self.canvas.drawString(550, 160, 'Share Gamma Exposure PP: {}'.format(round(shares)))


        self.canvas.setFont('Helvetica', 9)
        self.canvas.drawString(10, 160, 'MARKET MAKER INVENTORY')
        self.canvas.drawString(10, 145, 'Notional Delta:')
        self.canvas.drawString(10, 130, 'Notional Gamma: ')
        self.canvas.drawString(10, 115, 'Notional DdelV: ')
        self.canvas.drawString(10, 100, 'Net Vega Traded: ')

        self.canvas.line(x1=0, x2=260, y1=90, y2=90)
        self.canvas.drawCentredString(65, 80, 'CALLS')
        # self.canvas.line(x1=45, x2=45, y1=90, y2=77.5)
        # self.canvas.line(x1=85, x2=85, y1=90, y2=77.5)

        self.canvas.drawCentredString(195, 80, 'PUTS')
        # self.canvas.line(x1=175, x2=175, y1=90, y2=77.5)
        # self.canvas.line(x1=215, x2=215, y1=90, y2=77.5)

        self.canvas.line(x1=0, x2=260, y1=77.5, y2=77.5)
        self.canvas.line(x1=130, x2=130, y1 = 90, y2= 77.5 )

        self.canvas.setFont('Helvetica', 7)
        self.canvas.line(x1=125, x2=135, y1=65, y2=77.5)
        self.canvas.drawString(126, 71, 'B')
        self.canvas.drawString(130, 67, 'S')
        self.canvas.setFont('Helvetica', 9)

        xstart = 130
        ystart = 55
        for letter in ['B', 'S', 'B', 'S']:
            self.canvas.drawCentredString(xstart, ystart, letter)
            ystart -= 13
            if ystart == 29:
                ystart -= 11



        xstart = 65 - 40
        for string in ['ITM', 'ATM', 'OTM']:

            self.canvas.line(x1=xstart-20, x2=xstart-20, y1=77.5, y2=0)
            self.canvas.drawCentredString(xstart, 67.5, string)
            self.canvas.line(x1=xstart+20, x2=xstart+20, y1=77.5, y2=0)
            xstart += 40

        xstart = 195 - 40
        for string in ['ITM', 'ATM', 'OTM']:
            self.canvas.line(x1=xstart - 20, x2=xstart - 20, y1=77.5, y2=0)
            self.canvas.drawCentredString(xstart, 67.5, string)
            self.canvas.line(x1=xstart + 20, x2=xstart + 20, y1=77.5, y2=0)
            xstart += 40

        self.canvas.line(x1=0, x2=260, y1=65, y2=65)
        self.canvas.line(x1=0, x2=260, y1=52, y2=52)
        # self.canvas.line(x1=125, x2=125, y1=65, y2=0)
        # self.canvas.line(x1=135, x2=135, y1=65, y2=0)
        self.canvas.setFillColor('white')



        self.canvas.rect(5, 30, width=120, height=8, fill=1)

        self.canvas.rect(135, 30, width=120, height=8, fill=1)


        self.canvas.setFillColor('black')

        self.canvas.setFont('Helvetica', 8)
        self.canvas.drawCentredString(x=65, y=31.7, text='5-day Average')
        self.canvas.drawCentredString(x=195, y=31.7, text='5-day Average')
        self.canvas.setFont('Helvetica', 9)

        ycor = 160
        for item in data[:4]:
            print(item)
            color = 'red' if item < 0 else 'green'
            ycor -= 15
            self.canvas.setFillColor(aColor=color)
            self.canvas.drawRightString(250, ycor, '{}'.format(commify(round(item, 2))))

        xstart, ystart = 25, 55
        for item in data[4:-1]:
            print(item, data[4:-1].index(item))
            index = data[4:-1].index(item)
            color = 'red' if item < averages[index] else 'green'
            self.canvas.setFillColor(aColor=color)
            self.canvas.drawCentredString(xstart, ystart, '{}'.format(round(item, 1)))

            if xstart == 105:
                xstart += 50
            else:
                xstart += 40
            if xstart > 235:
                xstart = 25
                ystart -= 14.5

        xstart, ystart = 25, 18
        self.canvas.setFillColor('black')
        for item in averages:
            self.canvas.drawCentredString(xstart, ystart, '{}'.format(round(item, 1)))
            if xstart == 105:
                xstart += 50
            else:
                xstart += 40
            if xstart > 235:
                xstart = 25
                ystart -= 13.5
        self.canvas.line(x1=5, x2=260, y1=15, y2=15)

        self.canvas.rect(125, 30, width=10, height=8, fill=1)
        self.canvas.rect(255, 0, width=5, height=77, fill=1)

        price = Security(self.symbol).price

        first, change, change_percent = False, 0, 0
        try:
            change = (price - last5[1][-1])
            change_percent = change / last5[1][-1] * 100
        except IndexError:
            first = True

        if not first:
            color = 'red' if change < 0 else 'green'
            self.canvas.setFillColor(color)
            self.canvas.setFont('Helvetica', 12)

            self.canvas.drawCentredString(x=585, y=575, text='{}'.format(round(change, 2)))
            self.canvas.drawCentredString(x=635, y=575, text='{} %'.format(round(change_percent, 2)))
            
        self.canvas.setFillColor('black')
        self.canvas.drawCentredString(x=535, y=575, text='{}'.format(price))
        self.canvas.drawCentredString(400, 575, '{} ({})'.format(stock_info[self.symbol], self.symbol))



        self.canvas.line(x1=0, x2=800, y1=611, y2=611)
        self.canvas.line(x1=0, x2=800, y1=1, y2=1)




    def _second_page_graphs(self):
        cwd = os.getcwd()
        os.mkdir('bsgraphs')
        os.chdir('bsgraphs')
        xstart, ystart = 10, 460
        for i in [1,2,3,4,5,6]:
            fig, ax = plt.subplots(figsize=(8, 5))
            BuySellLine(symbol=self.symbol, axis=ax, mode=i, labels='False')
            fig.savefig('{}.png'.format(i), bbox_inches='tight')

            self.canvas.drawImage('{}.png'.format(i), x=xstart, y=ystart, width=250, height=150)
            self.canvas.line(x1=xstart+255, x2=xstart+255, y1=ystart+150, y2=ystart)
            xstart += 265
            if xstart > 600:
                xstart = 10
                ystart = 0

        os.chdir(cwd)
        shutil.rmtree('bsgraphs')




    def _second_page_data(self):
        months_abbr = {'01': 'JAN', '02': 'FEB', '03': 'MAR', '04': 'APR', '05': 'MAY', '06': 'JUN', '07': 'JUL',
                       '08': 'AUG', '09': 'SEP', '10': 'OCT', '11': 'NOV', '12': 'DEC'}
        calls = self._get_dics()
        puts = self._get_dics('PUT')

        calls = self.order_by_volume(calls)
        puts = self.order_by_volume(puts)

        print(calls, puts)

        self.canvas.line(x1=0, x2=800, y1=150, y2=150)
        self.canvas.line(x1=0, x2=800, y1=460, y2=460)

        self.canvas.line(x1=0, x2=800, y1=610, y2=610)
        self.canvas.line(x1=0, x2=800, y1=1, y2=1)

        self.canvas.rect(x=0, y=0, width=5, height=615, fill=1)
        self.canvas.rect(x=787, y=0, width=5, height=615, fill=1)

        self.canvas.rect(x=0, y=455.5, width=800, height=3.5, fill=1)
        self.canvas.rect(x=0, y=150, width=800, height=3.5, fill=1)


        self.canvas.setFont('Helvetica-Bold', 13)
        self.canvas.drawCentredString(200, 440, 'HIGHEST VOLUME CALLS')
        self.canvas.drawCentredString(600, 440, 'HIGHEST VOLUME PUTS')
        self.canvas.line(x1=0, x2=800, y1=435, y2=435)
        self.canvas.line(x1=405, x2=405, y1=455, y2=150)


        self.canvas.setFont('Helvetica', 12)


        # CALL TABLE

        xstart, ystart = 150, 395
        self.canvas.drawString(xstart - 120, ystart + 20, 'CONTRACT')
        self.canvas.line(x1=xstart + 5, x2 = xstart+5, y1=ystart+30, y2 =ystart-225)
        self.canvas.drawRightString(xstart + 60, ystart + 20, 'VOLUME')
        self.canvas.line(x1=xstart + 65, x2=xstart + 65, y1=ystart + 30, y2=ystart - 225)
        self.canvas.drawRightString(xstart + 120, ystart + 20, 'VWAP')
        self.canvas.line(x1=xstart + 125, x2=xstart + 125, y1=ystart + 30, y2=ystart - 225)
        self.canvas.drawRightString(xstart + 220, ystart + 20, '$$ VOLUME')
        self.canvas.line(x1=xstart + 225, x2=xstart + 225, y1=ystart + 30, y2=ystart - 225)

        self.canvas.line(x1=xstart-120, x2 = xstart + 225, y1 = ystart+15, y2=ystart+15)
        for item in calls:
            optype = 'C'
            volume, avg_price, strike = item[0], item[1], item[2]
            expiration = item[3].split('-')

            expiration = expiration[2] + ' ' + months_abbr[expiration[1]] + ' ' + expiration[0] + ' ' + str(strike) + ' ' + optype
            value = commify(round((round(avg_price, 2) * 100 * volume), 2))


            self.canvas.drawRightString(xstart, ystart, text=expiration)
            self.canvas.drawRightString(xstart + 60, ystart, text='{}'.format(volume))
            self.canvas.drawRightString(xstart + 120, ystart, text='{}'.format(round(avg_price, 2)))
            self.canvas.drawRightString(xstart + 220, ystart, text='{}'.format(value))
            ystart -= 20

        self.canvas.drawRightString(x=xstart, y=ystart - 18, text='{}'.format("TOTALS"))
        sum_volume = sum([item[0] for item in calls])
        sum_dollars = commify(round(sum([item[0] * item[1] * 100 for item in calls]), 2))
        # ultimate_average = round(np.mean([item[1] for item in calls]), 2)
        # self.canvas.drawRightString(x=xstart + 120, y=ystart - 18, text='{}'.format(ultimate_average))

        self.canvas.drawRightString(x=xstart + 220, y=ystart-18, text='{}'.format(sum_dollars))
        self.canvas.drawRightString(x=xstart + 60, y=ystart - 18, text='{}'.format(sum_volume))
        self.canvas.line(x1=xstart - 120, x2=xstart + 225, y1=ystart - 5, y2=ystart - 5)


        # PUT TABLE

        xstart, ystart = 550, 395
        self.canvas.drawString(xstart - 120, ystart + 20, 'CONTRACT')
        self.canvas.line(x1=xstart + 5, x2=xstart + 5, y1=ystart + 30, y2=ystart - 225)
        self.canvas.drawRightString(xstart + 60, ystart + 20, 'VOLUME')
        self.canvas.line(x1=xstart + 65, x2=xstart + 65, y1=ystart + 30, y2=ystart - 225)
        self.canvas.drawRightString(xstart + 120, ystart + 20, 'VWAP')
        self.canvas.line(x1=xstart + 125, x2=xstart + 125, y1=ystart + 30, y2=ystart - 225)
        self.canvas.drawRightString(xstart + 220, ystart + 20, '$$ VOLUME')
        self.canvas.line(x1=xstart + 225, x2=xstart + 225, y1=ystart + 30, y2=ystart - 225)

        self.canvas.line(x1=xstart - 120, x2=xstart + 225, y1=ystart + 15, y2=ystart + 15)

        for item in puts:
            optype = 'P'
            volume, avg_price, strike = item[0], item[1], item[2]
            expiration = item[3].split('-')

            expiration = expiration[2] + ' ' + months_abbr[expiration[1]] + ' ' + expiration[0] + ' ' + str(
                strike) + ' ' + optype
            value = commify(round((avg_price * 100 * volume), 2))

            self.canvas.drawRightString(xstart, ystart, text=expiration)
            self.canvas.drawRightString(xstart + 60, ystart, text='{}'.format(volume))
            self.canvas.drawRightString(xstart + 120, ystart, text='{}'.format(round(avg_price, 2)))
            self.canvas.drawRightString(xstart + 220, ystart, text='{}'.format(value))
            ystart -= 20

        self.canvas.drawRightString(x=xstart, y=ystart-18, text='{}'.format("TOTALS"))
        sum_volume = sum([item[0] for item in puts])
        sum_dollars = commify(round(sum([item[0] * item[1] * 100 for item in puts]), 2))
        # ultimate_average = round(np.mean([item[1] for item in puts]), 2)
        # self.canvas.drawRightString(x=xstart + 120, y=ystart - 18, text='{}'.format(ultimate_average))
        self.canvas.drawRightString(x=xstart + 220, y=ystart - 18, text='{}'.format(sum_dollars))
        self.canvas.drawRightString(x=xstart + 60, y=ystart -18, text='{}'.format(sum_volume))
        self.canvas.line(x1=xstart - 120, x2=xstart + 225, y1=ystart - 5, y2=ystart - 5)

        return calls, puts




    def _get_dics(self, optype = 'CALL'):
        symbol = self.symbol
        if symbol == '$SPX.X':
            symbol = '^SPX'

        expirations = {}

        db = sqlite3.connect('/Users/davesmith/Desktop/Hau DataCenter/HAU_TRADE_DATABASE.sqlite')
        cursor=db.cursor()
        sql = 'SELECT expiration, strike, trade_size, trade_price FROM Trades WHERE underlying_symbol = ? and quote_datetime > ? and option_type = ?'
        cursor.execute(sql, (symbol, self.date, optype))

        memory = [item for item in cursor]

        for item in memory:

            try:
                expiration_dic_keys = expirations[item[0]]


            except KeyError:
                expirations[item[0]] = {}
                expirations[item[0]][item[1]] = [item[2], (item[3]*item[2])]

            else:
                try:
                    strike_data = expiration_dic_keys[item[1]]
                    strike_data[0] += item[2]
                    strike_data[1] += (item[3] * item[2])

                except KeyError:
                    expiration_dic_keys[item[1]] = [item[2], (item[3]*item[2])]

        return expirations

    def order_by_volume(self, dic: dict):
        ordered = []
        for exp in dic:
            for strike in dic[exp]:
                volume, pricem = dic[exp][strike]
                volume, price = volume, pricem/volume
                ordered.append((volume, price, strike, exp))
        ordered = list(reversed(sorted(ordered, key=lambda x: x[0])))
        return ordered[:10]

    def plot_color_pages(self):
        counter = 0
        cwd = os.getcwd()
        os.mkdir('colorgraphs')
        os.chdir('colorgraphs')

        # HOUSEKEEPING--------------------------------
        self.canvas.setFillColor('black')
        self.canvas.rect(x=0, y=610, width=800, height=3, fill=1)
        self.canvas.rect(x=0, y=0, width=800, height=2, fill=1)

        self.canvas.rect(x=0, y=0, width=5, height=615, fill=1)
        self.canvas.rect(x=787, y=0, width=5, height=615, fill=1)
        # HOUSEKEEPING---------------------------------------------

        pages = 0

        for item in self.highestcalls:
            optype = 'C'
            volume, avg_price, strike = item[0], item[1], item[2]
            raw_expiration = item[3]
            expiration = item[3].split('-')
            string_expiration = expiration[2] + ' ' + self.months_abbr[expiration[1]] + ' ' + expiration[0] + ' ' + str(
                strike) + ' ' + optype

            if self.ltracker is not None:
                date = self.date.split(' ')[0]
                fig = self.ltracker.plot(expiry = raw_expiration, strike=str(strike) + '00', date_time_low=date + ' 08:00:00.000',
                                         date_time_high=date + ' 17:00:00.000', option_type='CALL', format_date_time=True )
                fig.savefig('{}.png'.format(string_expiration), bbox_inches='tight')
                # plt.close(fig=fig)
            else:
                fig, ax=plt.subplots()
                fig.savefig('{}.png'.format(string_expiration), bbox_inches='tight')
                # plt.close(fig=fig)

            self.canvas.setFont('Helvetica', 15)

            if counter == 0:
                y= 590
            else:
                y=300
            self.canvas.drawString(10, y, text='{}'.format(string_expiration))
            self.canvas.line(x1=0, x2=800, y1=y-5, y2=y-5)
            if counter != 0:
                self.canvas.line(x1=0, x2=800, y1=y + 15, y2=y + 15)


            if counter == 0:
                x, y = 20, 320
            else:
                x, y = 20, 10
            self.canvas.drawImage('{}.png'.format(string_expiration), x=x, y=y, width=760, height=260)
            counter += 1
            if counter == 2:
                pages += 1
                if pages <=  9:
                    self.canvas.showPage()
                    # HOUSEKEEPING--------------------------------
                    self.canvas.setFillColor('black')
                    self.canvas.rect(x=0, y=610, width=800, height=3, fill=1)
                    self.canvas.rect(x=0, y=0, width=800, height=2, fill=1)

                    self.canvas.rect(x=0, y=0, width=5, height=615, fill=1)
                    self.canvas.rect(x=787, y=0, width=5, height=615, fill=1)
                    # HOUSEKEEPING---------------------------------------------
                counter = 0

        for item in self.highestputs:
            optype = 'P'
            volume, avg_price, strike = item[0], item[1], item[2]
            raw_expiration = item[3]
            expiration = item[3].split('-')
            string_expiration = expiration[2] + ' ' + self.months_abbr[expiration[1]] + ' ' + expiration[0] + ' ' + str(
                strike) + ' ' + optype

            if self.ltracker is not None:
                date = self.date.split(' ')[0]

                fig = self.ltracker.plot(expiry=raw_expiration, strike=str(strike) + '00', date_time_low=date + ' 08:00:00.000',
                                         date_time_high=date + ' 17:00:00.000', option_type='PUT',
                                         format_date_time=True)
                fig.savefig('{}.png'.format(string_expiration), bbox_inches='tight')
                # plt.close(fig=fig)
            else:
                fig, ax = plt.subplots()
                fig.savefig('{}.png'.format(string_expiration), bbox_inches='tight')
                # plt.close(fig=fig)

            self.canvas.setFont('Helvetica', 15)
            if counter == 0:
                y = 590
            else:
                y = 300
            self.canvas.drawString(10, y, text='{}'.format(string_expiration))
            self.canvas.line(x1=0, x2=800, y1=y - 5, y2=y - 5)
            if counter != 0:
                self.canvas.line(x1=0, x2=800, y1=y + 15, y2=y + 15)

            if counter == 0:
                x, y = 20, 320
            else:
                x, y = 20, 20
            self.canvas.drawImage('{}.png'.format(string_expiration), x=x, y=y, width=760, height=260)
            counter += 1
            if counter == 2:
                pages += 1
                if pages <= 9:
                    self.canvas.showPage()
                    # HOUSEKEEPING--------------------------------
                    self.canvas.setFillColor('black')
                    self.canvas.rect(x=0, y=610, width=800, height=3, fill=1)
                    self.canvas.rect(x=0, y=0, width=800, height=2, fill=1)

                    self.canvas.rect(x=0, y=0, width=5, height=615, fill=1)
                    self.canvas.rect(x=787, y=0, width=5, height=615, fill=1)
                    # HOUSEKEEPING---------------------------------------------
                counter = 0
        os.chdir(cwd)
        shutil.rmtree('colorgraphs')






#
#
# with shelve.open('/Users/davesmith/Desktop/Hau DataCenter/PDF/Ltrackerstsla') as db:
#     tracker = db['TSLA']
# #
# # #
# # #
# # #
# # #
# # #
# # #
# # #
# # # #
# # # # tracker.to_gui()
# # #
# # #
# # #
# # #
# # # #
# if __name__ == '__main__':
#
#     PDF('TSLA', '2020-08-31', strike_margin=0.15, ltracker=tracker)
