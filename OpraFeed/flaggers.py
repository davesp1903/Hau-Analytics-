
from OpraFeed.OpraFeeds import Trade, OpraFeed
import matplotlib.dates as dates
import datetime


def cross_the_spread(trade: Trade):
    flagged, inference = False, 'NONE'
    if trade.trade_price == trade.best_ask or float(trade.trade_price) > float(trade.best_ask):
        flagged, inference = True, 'BUY'

    if trade.trade_price == trade.best_bid or float(trade.trade_price) < float(trade.best_bid):
        flagged, inference = True, 'SELL'

    trade.set_inference(inference)

    return flagged, inference


def cross_spread_bid_ask_liquidity(trade:Trade, feed:OpraFeed):
    flagged, inference = False, 'NONE'
    if trade.trade_price == trade.best_ask or float(trade.trade_price) > float(trade.best_ask):
        flagged, inference = True, 'BUY'

    if trade.trade_price == trade.best_bid or float(trade.trade_price) < float(trade.best_bid):
        flagged, inference = True, 'SELL'

    trade.set_inference(inference)

    if trade.inference == 'NONE':

        spread = abs((float(trade.best_bid) - float(trade.best_ask)))

        try:
            if abs(float(trade.trade_price) - float(trade.best_ask)) / spread <= 0.05:
                flagged, inference = True, 'BUY'
        except ZeroDivisionError:
            pass
        try:
            if abs(float(trade.trade_price) - float(trade.best_bid)) / spread <= 0.05:
                flagged, inference = True, 'SELL'
        except ZeroDivisionError:
            pass

    trade.set_inference(inference)

    if trade.inference == 'NONE':

        current_bid, current_ask = trade.best_bid, trade.best_ask
        current_bid_size, current_ask_size = sum([int(trade.by_exchange[exchange][0]) for exchange in trade.by_exchange if trade.by_exchange[exchange][1].strip('\n') == trade.best_bid]),\
                                             sum([int(trade.by_exchange[exchange][2]) for exchange in trade.by_exchange if trade.by_exchange[exchange][3].strip('\n') == trade.best_ask])

        time_stamps = feed.liquidity_tracker.expirations[trade.expiration].strikes[trade.strike].time_stamps
        stamps_list = sorted(time_stamps.keys())
        i = 1
        try:
            next_stamp = stamps_list[stamps_list.index(trade.quote_datetime) + i]
            while trade.option_type not in time_stamps[next_stamp].keys():
                next_stamp = stamps_list[stamps_list.index(trade.quote_datetime) + i]
                i += 1
        except IndexError:
            return flagged, inference

        next_bid, next_ask = time_stamps[next_stamp][trade.option_type]['bid'], time_stamps[next_stamp][trade.option_type]['ask']
        next_bid_size, next_ask_size = time_stamps[next_stamp][trade.option_type]['bid_size'], time_stamps[next_stamp][trade.option_type]['ask_size']
        # print(current_ask_size, current_bid_size, current_ask, current_bid)
        # print(next_bid_size, next_ask_size, next_bid, next_ask)


        volume_cut_off_ratio = 2.0
        time_difference = dates.date2num(datetime.datetime.strptime(next_stamp, '%Y-%m-%d %H:%M:%S.%f')) - dates.date2num(datetime.datetime.strptime(trade.quote_datetime, '%Y-%m-%d %H:%M:%S.%f'))


        if (next_bid > current_bid or next_ask > current_ask) and (trade.trade_size >= 200 and time_difference < .00071):
            flagged, inference = True, 'BUY'
        elif (next_bid < current_bid or next_ask < current_ask) and (trade.trade_size >= 200 and time_difference < .00071):
            flagged, inference = True, 'SELL'
        elif (next_bid > current_bid or next_ask > current_ask) and (trade.trade_size >= 500 and time_difference < .00140):
            flagged, inference = True, 'BUY'
        elif (next_bid < current_bid or next_ask < current_ask) and (trade.trade_size >= 500 and time_difference < .00140):
            flagged, inference = True, 'SELL'
        elif trade.trade_size > current_bid_size:
            flagged, inference, = True, 'BUY'
        elif trade.trade_size > current_ask_size:
            flagged, inference, = True, 'SELL'
        else:
            try:
                if ((current_bid_size - next_bid_size) / trade.trade_size * 100) / ((current_ask_size - next_ask_size) / trade.trade_size * 100) >= volume_cut_off_ratio:
                    flagged, inference = True, 'BUY'
                elif ((current_ask_size - next_ask_size) / trade.trade_size * 100) / ((current_bid_size - next_bid_size) / trade.trade_size * 100) >= volume_cut_off_ratio:
                    flagged, inference = True, 'SELL'
            except ZeroDivisionError:
                flagged, inference = False, 'NONE'


    trade.set_inference(inference)

    return flagged, inference


def pure_sabr_curve(trade:Trade, feed:OpraFeed):
    flagged, inference = False, 'NONE'
    if trade.trade_price == trade.best_ask or float(trade.trade_price) > float(trade.best_ask):
        flagged, inference = True, 'BUY'

    if trade.trade_price == trade.best_bid or float(trade.trade_price) < float(trade.best_bid):
        flagged, inference = True, 'SELL'

    trade.set_inference(inference)

    if trade.inference == 'NONE':


        proper_curve = feed.CurveArchive.curves[trade.expiration]
        log = proper_curve.sabr_log
        position = sorted(log.keys()).index(trade.quote_datetime)
        prev_curve_position = sorted(log.keys())[position - 1]
        sabr_model = log[prev_curve_position]

        if sabr_model is not None:

            vol = sabr_model.volatility_from_K(K=float(trade.strike))
            if trade.volatility > vol:
                flagged, inference = True, 'BUY'
            elif trade.volatility < vol:
                flagged, inference = True, 'SELL'

            trade.set_inference(inference)
        else:
            pass

    return flagged, inference


def pure_poly_curve(trade:Trade, feed:OpraFeed):
    flagged, inference = False, 'NONE'
    if trade.trade_price == trade.best_ask or float(trade.trade_price) > float(trade.best_ask):
        flagged, inference = True, 'BUY'

    if trade.trade_price == trade.best_bid or float(trade.trade_price) < float(trade.best_bid):
        flagged, inference = True, 'SELL'

    trade.set_inference(inference)

    if trade.inference == 'NONE':

        proper_curve = feed.CurveArchive.curves[trade.expiration]
        log = proper_curve.chronolog
        position = sorted(log.keys()).index(trade.quote_datetime)
        prev_curve_position = sorted(log.keys())[position - 1]
        poly_model = log[prev_curve_position]

        if poly_model is not None:

            vol = poly_model(float(trade.strike))
            if trade.volatility > vol:
                flagged, inference = True, 'BUY'
            elif trade.volatility < vol:
                flagged, inference = True, 'SELL'

            trade.set_inference(inference)
        else:
            pass

    return flagged, inference


def dual_curve_magic(trade:Trade, feed:OpraFeed):

    flagged, inference = False, 'NONE'
    if trade.trade_price == trade.best_ask or float(trade.trade_price) > float(trade.best_ask):
        flagged, inference = True, 'BUY'

    if trade.trade_price == trade.best_bid or float(trade.trade_price) < float(trade.best_bid):
        flagged, inference = True, 'SELL'

    trade.set_inference(inference)

    if trade.inference == 'NONE':

        proper_curve = feed.CurveArchive.curves[trade.expiration]
        actives = proper_curve.active_trade_chronolog[trade.quote_datetime]

        poly_log = proper_curve.chronolog
        position = sorted(poly_log.keys()).index(trade.quote_datetime)
        prev_curve_position = sorted(poly_log.keys())[position - 1]
        poly_model = poly_log[prev_curve_position]

        sabr_log = proper_curve.sabr_log
        position = sorted(sabr_log.keys()).index(trade.quote_datetime)
        prev_curve_position = sorted(sabr_log.keys())[position - 1]
        sabr_model = sabr_log[prev_curve_position]

        if sabr_model is not None and poly_model is not None:
            low, high = float(trade.strike) - (float(trade.strike) * 0.05), float(trade.strike) + (float(trade.strike) * 0.05)
            test_trades = [active_trade for active_trade in actives if low <= float(active_trade.strike) <= high]
            poly_residuals = [abs(test.fill_iv - poly_model(float(test.strike)))**2 for test in test_trades]
            sabr_residuals = [abs(test.fill_iv - sabr_model.volatility_from_K(K=float(test.strike)))**2 for test in test_trades]
            sabr = True if sum(sabr_residuals) < sum(poly_residuals) else False

            if sabr is True:
                vol = sabr_model.volatility_from_K(K=float(trade.strike))
                if trade.volatility > vol:
                    flagged, inference = True, 'BUY'
                elif trade.volatility < vol:
                    flagged, inference = True, 'SELL'

                else:
                    pass

                trade.set_inference(inference)

            else:
                vol = poly_model(float(trade.strike))
                if trade.volatility > vol:
                    flagged, inference = True, 'BUY'
                elif trade.volatility < vol:
                    flagged, inference = True, 'SELL'
                else:
                    pass

                trade.set_inference(inference)
        else:
            pass

    return flagged, inference



