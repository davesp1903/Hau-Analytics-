import numpy as np
import scipy.stats as si



risk_free_rate = 0.000
dividends = {'AAPL': 0.0105, 'MSFT': 0.0134, 'BAC': 0.0299, 'TSLA': 0.0000, 'FB': 0.0000, '$SPX.X': 0.0000, 'QQQ': 0.0000, '^SPX': 0.0000, 'GLD': 0.000 }


def iv_from_price(option_price, S, K, T, q, r=risk_free_rate, option_type='CALL', cost_of_carry_type='STOCK'):
    sigma_range = range(10000000)

    if q != 0:
        cost_of_carry_type = 'DIVIDEND'
    else:
        cost_of_carry_type = cost_of_carry_type

    def search(option_price_to_find, rang, cost_of_carry_type=cost_of_carry_type):

        rang1 = rang
        midpoint = len(rang1) // 2

        upper = rang1[midpoint::]
        lower = rang1[0:midpoint]

        test_sigma = rang1[midpoint]

        call = BlackSholesMerton(S=S, K=K, T=T, sigma=test_sigma/10000, r=r, q=q, cost_of_carry_type=cost_of_carry_type).Premium
        put = BlackSholesMerton(S=S, K=K, T=T, sigma=test_sigma/10000, r=r, q=q, option_type='PUT', cost_of_carry_type=cost_of_carry_type).Premium
        sigma = test_sigma/10000

        if option_price_to_find == 0.0:
            return 0.00

        if midpoint == 0:

            return sigma

        if option_type == 'CALL':

            if call == option_price_to_find:

                return sigma
            elif call < option_price_to_find:
                return search(option_price_to_find, upper)
            elif call > option_price_to_find:
                return search(option_price_to_find, lower)
        else:

            if put == option_price_to_find:

                return sigma
            elif put < option_price_to_find:
                return search(option_price_to_find, upper)
            elif put > option_price_to_find:
                return search(option_price_to_find, lower)

    vol = search(option_price, sigma_range)
    if vol is None or vol <= .001:
        vol = 0.001
    return vol


def trading_days_from_expiration(today, expiration):

    days_until_expiration = 1
    now_year, now_month, now_day = today.split('-')
    exp_year, exp_month, exp_day = expiration.split('-')
    months_days = {1: 21, 2: 19, 3: 22, 4: 21, 5: 20, 6: 22, 7: 22, 8: 21, 9: 21, 10: 22, 11: 20, 12: 22}

    year_diff = int(exp_year) - int(now_year)
    month_diff = int(exp_month) - int(now_month)
    if month_diff < 0:
        if year_diff == 1:
            month_diff = abs(12 - abs(int(exp_month) - int(now_month)))
        else:
            month_diff = abs((12 * year_diff) - abs(int(exp_month) - int(now_month)))
    else:
        month_diff += 12 * year_diff

    counter = 0
    month = int(now_month)
    while counter < month_diff:
        days_until_expiration += months_days[int(month)]
        counter += 1
        month += 1
        if month == 13:
            month = 1
    days_until_expiration -= int(now_day)
    days_until_expiration += int(exp_day)

    return days_until_expiration


def calendar_days_from_expiration(today, expiration):
    days_until_expiration = 1
    now_year, now_month, now_day = today.split('-')
    exp_year, exp_month, exp_day = expiration.split('-')
    months_days = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

    year_diff = int(exp_year) - int(now_year)
    month_diff = int(exp_month) - int(now_month)
    if month_diff < 0:
        if year_diff == 1:
            month_diff = abs(12 - abs(int(exp_month) - int(now_month)))
        else:
            month_diff = abs((12 * year_diff) - abs(int(exp_month) - int(now_month)))
    else:
        month_diff += 12 * year_diff

    counter = 0
    month = int(now_month)
    while counter < month_diff:
        days_until_expiration += months_days[int(month)]
        counter += 1
        month += 1
        if month == 13:
            month = 1
    days_until_expiration -= int(now_day)
    days_until_expiration += int(exp_day)

    return days_until_expiration


class BlackSholesMerton:

    def __init__(self, S, K, r, q, T, sigma, option_type='CALL', cost_of_carry_type='STOCK'):
        self._cost_of_carry_type = cost_of_carry_type.upper()

        if q != 0:
            self._cost_of_carry_type = 'DIVIDEND'

        if option_type.upper() in ('C', 'CALL', 'CAL'):
            self.option_type = 'CALL'
        else:
            self.option_type = 'PUT'

        self.S = S
        self.K = K
        self.r = r
        self.q = q
        self.b = self._get_b()
        self.T = T
        self.sigma = sigma

        self.d1 = self._get_d1()
        self.d2 = self._get_d2()

        self.Premium = self._get_premium()

        self.Delta = self._get_delta()
        self.Gamma = self._get_gamma()

        self.Vega = self._get_vega() / 100
        self.Theta = self._get_theta() / 365                #DAILY THETA

        self.Rho = self._get_rho() / 100
        self.DdelV = self._get_DdelV() / 100
        self.DdelT = self._get_DdelT()
        self.Alpha = self._get_alpha() / 100



    def _get_b(self):
        if self._cost_of_carry_type == 'STOCK':
            b = self.r
        elif self._cost_of_carry_type == 'DIVIDEND':
            b = self.r - self.q
        elif self._cost_of_carry_type == 'FUTURE':
            b = 0
        else:
            b = None
        assert b is not None, 'b parameter returning none, set cost_of_carry_type to stock, dividend, or future'
        return b

    def _get_d1(self):
        d1 = (np.log(self.S / self.K) + (self.b + (0.5 * self.sigma ** 2)) * self.T) / (self.sigma * np.sqrt(self.T))
        return d1

    def _get_d2(self):
        d2 = (np.log(self.S / self.K) + (self.b - (0.5 * self.sigma ** 2)) * self.T) / (self.sigma * np.sqrt(self.T))
        return d2

    def _get_premium(self):
        c = (self.S * np.exp((self.b - self.r) * self.T) * si.norm.cdf(self.d1)) - (self.K * np.exp(-self.r * self.T) * si.norm.cdf(self.d2))
        p = -(self.S * np.exp((self.b - self.r) * self.T) * si.norm.cdf(-self.d1)) + (self.K * np.exp(-self.r * self.T) * si.norm.cdf(-self.d2))
        # print(c, p)
        return c if self.option_type == 'CALL' else p

        # if self.option_type == 'CALL':
        #     premium = (self.S * si.norm.cdf(self.d1, 0.0, 1.0) - self.K * np.exp(-self.r * self.T) * si.norm.cdf(self.d2, 0.0, 1.0))
        # else:
        #     premium = (self.K * np.exp(-self.r * self.T) * si.norm.cdf(-self.d2, 0.0, 1.0) - self.S * si.norm.cdf(-self.d1, 0.0, 1.0))
        # return premium

    def _get_delta(self):
        return np.exp((self.b - self.r) * self.T) * si.norm.cdf(self.d1, 0.0, 1.0) if self.option_type == 'CALL' else -np.exp((self.b - self.r) * self.T) * si.norm.cdf(-self.d1, 0.0, 1.0)

    def _get_gamma(self):
        return (np.exp((self.b - self.r) * self.T) * si.norm.pdf(self.d1, 0.0, 1.0)) / (self.S * self.sigma * np.sqrt(self.T))

    def _get_vega(self):
        return self.S * np.exp((self.b - self.r) * self.T) * si.norm.pdf(self.d1, 0.0, 1.0) * np.sqrt(self.T)

    def _get_theta(self):
        ctheta = - ((self.S * self.sigma * np.exp((self.b-self.r)*self.T) *
                     si.norm.pdf(self.d1, 0.0, 1.0)) / 2 * np.sqrt(self.T)) - (self.S*(self.b - self.r)
                 * np.exp((self.b-self.r) * self.T) * si.norm.cdf(self.d1, 0.0, 1.0)) - (-self.r * self.K * np.exp(-self.r * self.T) * si.norm.cdf(self.d2))
        ptheta = - ((self.S * self.sigma * np.exp((self.b-self.r)*self.T) *
                     si.norm.pdf(self.d1, 0.0, 1.0)) / 2 * np.sqrt(self.T)) + (self.S*(self.b - self.r)
                 * np.exp((self.b-self.r) * self.T) * si.norm.cdf(-self.d1, 0.0, 1.0)) + (-self.r * self.K * np.exp(-self.r * self.T) * si.norm.cdf(-self.d2))
        return ctheta if self.option_type == 'CALL' else ptheta

    def _get_rho(self):
        if self._cost_of_carry_type != 'FUTURE':
            crho = self.T * self.K * np.exp((-self.r * self.T)) * si.norm.cdf(self.d2, 0.0, 1.0)
            prho = -self.T * self.K * np.exp((-self.r * self.T)) * si.norm.cdf(-self.d2, 0.0, 1.0)
        else:
            crho = - self.T * self.Premium
            prho = - self.T * self.Premium
        return crho if self.option_type == "CALL" else prho

    def _get_DdelV(self):
        vanna = - (np.exp((self.b - self.r) * self.T) * self.d2 * si.norm.pdf(self.d1, 0.0, 1.0)) / self.sigma
        return vanna

    def _get_DdelT(self):
        cddt = -np.exp((self.b - self.r) * self.T) * (si.norm.pdf(self.d1, 0.0, 1.0) * ((self.b / (self.sigma * np.sqrt(self.T))) - (self.d2 / 2 * self.T)) + ((self.b-self.r) * si.norm.cdf(self.d1, 0.0, 1.0)))
        pddt = np.exp((self.b - self.r) * self.T) * (si.norm.pdf(self.d1, 0.0, 1.0) * ((self.b / (self.sigma * np.sqrt(self.T))) - (self.d2 / 2 * self.T)) - ((self.b-self.r) * si.norm.cdf(-self.d1, 0.0, 1.0)))
        return cddt if self.option_type == 'CALL' else pddt

    def _get_alpha(self):
        return self.Vega * self.d1 * self.d2 / self.sigma

    def __str__(self):
        print('Price == {}'.format(self.Premium))
        print('Delta == {}'.format(self.Delta))
        print('Gamma == {}'.format(self.Gamma))
        print('Vega == {}'.format(self.Vega))
        print('Theta == {}'.format(self.Theta))
        print('Rho == {}'.format(self.Rho))
        print('DdeIV == {}'.format(self.DdelV))
        print('DdeIT == {}'.format(self.DdelT))
        print('Alpha == {}'.format(self.Alpha))
        return ''


# print(calendar_days_from_expiration(today='2020-05-26', expiration='2020-06-19'))
# print(calendar_days_from_expiration(today='2020-05-26', expiration='2020-06-19')/365)
# model = BlackSholesMerton(S=228.58, K=230.0, q=dividends['AAPL'], T=calendar_days_from_expiration(today='2020-06-13', expiration='2020-06-19')/365, r=risk_free_rate, sigma=.4462, option_type='CALL')
# print(model)
# print('old' + '{}'.format( old_iv_recursion(option_price=16.12885, s=290.45, k=275, t=5/365)))
# print('new' + ' {}'.format(iv_from_price(option_price=2.55, S=318.95, K=335, T=calendar_days_from_expiration(today='2020-05-26', expiration='2020-06-19')/365, r=risk_free_rate, q=dividends['AAPL'])))
# print(model.Vega * (model.d1 * model.d2 / model.sigma)/ 100)


# model = BlackSholesMerton(S=25.5, K=16.0, r=0, q=0, T=.005479, sigma=.15)
# print(model)














