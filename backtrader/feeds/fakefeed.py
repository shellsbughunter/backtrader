import datetime
import logging
import time

import backtrader as bt
from enum import Enum

_logger = logging.getLogger(__name__)


class FakeFeed(bt.DataBase):
    class State(Enum):
        BACKTEST = 0,
        BACKFILL = 1,
        LIVE = 2,

    params = (
        ('starting_value', 200),
        ('tick_interval', datetime.timedelta(seconds=25)),
        ('start_delay', 0),
        ('run_duration', datetime.timedelta(seconds=30)),  # only used when not backtest mode
        ('num_gen_bars', 10),  # number of bars to generate in backtest or backfill mode
        ('live', True),
    )

    def __init__(self):
        super(FakeFeed, self).__init__()

        self._last_delivered = None

        self._cur_value = None
        self._current_comp = 0
        self._num_bars_delivered = 0
        self._compression_in_effect = None
        self._backfill_curtime = None
        self._tmoffset = datetime.timedelta(seconds=-0.5)  # configure offset cause we are sending slightly delayed ticked data (of course!)
        self._start_ts = None  # time of the first call to _load to obey start_delay

    def start(self):
        super(FakeFeed, self).start()

        self._start_ts = datetime.datetime.now()
        self._cur_value = self.p.starting_value

    def islive(self):
        return self.p.live

    def _update_line(self, dt, value):
        _logger.debug(f"{self._name} - Updating line - Bar Time: {dt} - Value: {value}")

        #if dt.hour == 18:
        #    dt = dt.replace(hour=17, minute=35)
        self.lines.datetime[0] = bt.date2num(dt)
        self.lines.volume[0] = 0.0
        self.lines.openinterest[0] = 0.0

        # Put the prices into the bar
        self.lines.open[0] = value
        self.lines.high[0] = value
        self.lines.low[0] = value
        self.lines.close[0] = value
        self.lines.volume[0] = 0.0
        self.lines.openinterest[0] = 0.0

    def _load(self):
        now = datetime.datetime.now()
        if now - self._start_ts < datetime.timedelta(seconds=self.p.start_delay):
            return None

        bars_done = self._num_bars_delivered >= self.p.num_gen_bars

        if self.p.live:
            if now - self._start_ts > self.p.run_duration:
                return False
        else:
            if bars_done:
                return False

        if self.p.live:
            if bars_done:
                return self._load_live(now)
            else:
                return self._load_bar(now, True)
        else:
            return self._load_bar(now)

    def _load_bar(self, now, backfill=False):
        tf, comp = self._timeframe, self._compression
        if tf == bt.TimeFrame.Ticks:
            delta = self.p.tick_interval * comp
        elif tf == bt.TimeFrame.Seconds:
            delta = datetime.timedelta(seconds=comp)
        elif tf == bt.TimeFrame.Minutes:
            delta = datetime.timedelta(minutes=comp)
        elif tf == bt.TimeFrame.Days:
            delta = datetime.timedelta(days=comp)
        else:
            raise RuntimeError(f"{self._name} - Unsupported timeframe: {self.p.timeframe}")

        if self._last_delivered is None:
            if backfill:
                self._last_delivered = self._time_floored(now - delta * (self.p.num_gen_bars - 1), tf)
            else:
                self._last_delivered = self._time_floored(now, tf)

        self._last_delivered += delta

        _logger.info(f"{self._name} - Loading bar: {self._backfill_curtime}")
        self._update_line(self._last_delivered, self._cur_value)
        self._cur_value += 1
        self._num_bars_delivered += 1
        return True

    @staticmethod
    def _time_floored(now, timeframe):
        t = now
        if timeframe in [bt.TimeFrame.Seconds, bt.TimeFrame.Ticks]:
            t = t.replace(microsecond=0)
        elif timeframe in bt.TimeFrame.Minutes:  # Ticks get also floored to last full second
            t = t.replace(second=0, microsecond=0)
        elif timeframe == bt.TimeFrame.Days:
            t = t.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            raise Exception(f'TimeFrame {timeframe} not supported')
        return t

    def _load_live(self, now):
        tf = self.p.timeframe
        target_tf = self._timeframe

        comp = self.p.compression

        if self._last_delivered is None:
            # first run, fill last_delivered
            self._last_delivered = self._time_floored(now, tf)

        if tf == bt.TimeFrame.Ticks:
            if now - self._last_delivered < self.p.tick_interval:
                return None
            _logger.info(f"{self._name} - Delivering - now: {now} - lastDel: {self._last_delivered}")
            self._last_delivered += self.p.tick_interval
        else:
            if tf == bt.TimeFrame.Minutes:
                if now.minute == self._last_delivered.minute:
                    return None
                self._last_delivered += datetime.timedelta(minutes=1)
            elif tf == bt.TimeFrame.Days:
                if now.day == self._last_delivered.day:
                    return None
                self._last_delivered += datetime.timedelta(days=1)

        self._current_comp += 1

        if self._current_comp == comp:  # do not use self._compression as it is modified by resampler already
            self._current_comp = 0

            self._update_line(self._last_delivered, self._cur_value)
            self._cur_value += 1
            _logger.info(f"{self._name} - Tick delivered: {self._last_delivered}")
            return True
        else:
            return None

