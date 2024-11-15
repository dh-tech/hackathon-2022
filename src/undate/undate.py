import datetime
import re
from calendar import monthrange

# Pre 3.10 requires Union for multiple types, e.g. Union[int, None] instead of int | None
from typing import Dict, Optional, Union

from undate.converters.base import BaseDateConverter
from undate.date import ONE_DAY, ONE_MONTH_MAX, ONE_YEAR, Date, DatePrecision, Timedelta


class Undate:
    """object for representing uncertain, fuzzy or partially unknown dates"""

    DEFAULT_CONVERTER: str = "ISO8601"

    #: symbol for unknown digits within a date value
    MISSING_DIGIT: str = "X"

    earliest: Date
    latest: Date
    #: A string to label a specific undate, e.g. "German Unity Date 2022" for Oct. 3, 2022.
    #: Labels are not taken into account when comparing undate objects.
    label: Union[str, None] = None
    converter: BaseDateConverter
    #: precision of the date (day, month, year, etc.)
    precision: DatePrecision

    #: known non-leap year
    NON_LEAP_YEAR: int = 2022
    # numpy datetime is stored as 64-bit integer, so min/max
    # depends on the time unit; assume days for now
    # See https://numpy.org/doc/stable/reference/arrays.datetime.html#datetime-units
    # It just so happens that int(2.5e16) is a leap year, which is a weird default,
    # so let's increase our lower bound by one year.
    MIN_ALLOWABLE_YEAR = int(-2.5e16) + 1
    MAX_ALLOWABLE_YEAR = int(2.5e16)

    def __init__(
        self,
        year: Optional[Union[int, str]] = None,
        month: Optional[Union[int, str]] = None,
        day: Optional[Union[int, str]] = None,
        converter: Optional[BaseDateConverter] = None,
        label: Optional[str] = None,
    ):
        # keep track of initial values and which values are known
        # TODO: add validation: if str, must be expected length
        self.initial_values: Dict[str, Optional[Union[int, str]]] = {
            "year": year,
            "month": month,
            "day": day,
        }
        if day:
            self.precision = DatePrecision.DAY
        elif month:
            self.precision = DatePrecision.MONTH
        elif year:
            self.precision = DatePrecision.YEAR

        # special case: treat year = XXXX as unknown/none
        if year == "XXXX":
            year = None

        if year is not None:
            # could we / should we use str.isnumeric here?
            try:
                year = int(year)
                # update initial value since it is used to determine
                # whether or not year is known
                self.initial_values["year"] = year
                min_year = max_year = year
            except ValueError:
                # year is a string that can't be converted to int
                min_year = int(str(year).replace(self.MISSING_DIGIT, "0"))
                max_year = int(str(year).replace(self.MISSING_DIGIT, "9"))
        else:
            # use the configured min/max allowable years if we
            # don't have any other bounds
            min_year = self.MIN_ALLOWABLE_YEAR
            max_year = self.MAX_ALLOWABLE_YEAR

        # if month is passed in as a string but completely unknown,
        # treat as none
        # TODO: we should preserve this information somehow;
        # difference between just a year and and an unknown month within a year
        # maybe in terms of date precision ?
        if month == "XX":
            month = None

        min_month = 1
        max_month = 12
        if month is not None:
            try:
                # treat as an integer if we can
                month = int(month)
                # update initial value
                self.initial_values["month"] = month
                min_month = max_month = month
            except ValueError:
                # if not, calculate min/max for missing digits
                min_month, max_month = self._missing_digit_minmax(
                    str(month), min_month, max_month
                )

        # similar to month above — unknown day, but day-level granularity
        if day == "XX":
            day = None

        if isinstance(day, int) or isinstance(day, str) and day.isnumeric():
            day = int(day)
            # update initial value - fully known day
            self.initial_values["day"] = day
            min_day = max_day = day
        else:
            # if we have no day or partial day, calculate min / max
            min_day = 1
            # if we know year and month (or max month), calculate exactly
            if year and month and isinstance(year, int):
                _, max_day = monthrange(int(year), max_month)
            elif year is None and month:
                # If we don't have year and month,
                # calculate based on a known non-leap year
                # (better than just setting 31, but still not great)
                _, max_day = monthrange(self.NON_LEAP_YEAR, max_month)
            else:
                max_day = 31

            # if day is partially specified, narrow min/max further
            if day is not None:
                min_day, max_day = self._missing_digit_minmax(day, min_day, max_day)

        # TODO: special case, if we get a Feb 29 date with unknown year,
        # must switch the min/max years to known leap years!

        # for unknowns, assume smallest possible value for earliest and
        # largest valid for latest
        self.earliest = Date(min_year, min_month, min_day)
        self.latest = Date(max_year, max_month, max_day)

        if converter is None:
            #  import all subclass definitions; initialize the default
            converter_cls = BaseDateConverter.available_converters()[
                self.DEFAULT_CONVERTER
            ]
            converter = converter_cls()
        self.converter = converter

        self.label = label

    def __str__(self) -> str:
        # if any portion of the date is partially known, construct
        # pseudo ISO8601 format here, since ISO8601 doesn't support unknown digits
        # (temporary, should switch to default format that can handle it, e.g. EDTF)
        if any(self.is_partially_known(part) for part in ["year", "month", "day"]):
            # initial values could be either string or int
            year = self.initial_values["year"]
            month = self.initial_values["month"]
            day = self.initial_values["day"]
            # if integer, convert to string with correct number of digits
            # replace unknown year with - for --MM or --MM-DD format
            parts = [
                f"{year:04d}" if isinstance(year, int) else year or "-",
                f"{month:02d}" if isinstance(month, int) else month,
                f"{day:02d}" if isinstance(day, int) else day,
            ]
            # combine, skipping any values that are None
            return "-".join([str(p) for p in parts if p is not None])

        return self.converter.to_string(self)

    def __repr__(self) -> str:
        if self.label:
            return "<Undate '%s' (%s)>" % (self.label, self)
        return "<Undate %s>" % self

    @classmethod
    def parse(cls, date_string, format) -> Union["Undate", "UndateInterval"]:
        """parse a string to an undate or undate interval using the specified format;
        for now, only supports named converters"""
        converter_cls = BaseDateConverter.available_converters().get(format, None)
        if converter_cls:
            # NOTE: some parsers may return intervals; is that ok here?
            return converter_cls().parse(date_string)

        raise ValueError(f"Unsupported format '{format}'")

    def format(self, format) -> str:
        """format this undate as a string using the specified format;
        for now, only supports named converters"""
        converter_cls = BaseDateConverter.available_converters().get(format, None)
        if converter_cls:
            # NOTE: some parsers may return intervals; is that ok here?
            return converter_cls().to_string(self)

        raise ValueError(f"Unsupported format '{format}'")

    def _comparison_type(self, other: object) -> "Undate":
        """Common logic for type handling in comparison methods.
        Converts to Undate object if possible, otherwise raises
        NotImplemented error.  Currently only supports conversion
        from :class:`datetime.date`
        """

        # support datetime.date by converting to undate
        if isinstance(other, datetime.date):
            other = Undate.from_datetime_date(other)

        # recommended to support comparison with arbitrary objects
        if not isinstance(other, Undate):
            return NotImplemented

        return other

    def __eq__(self, other: object) -> bool:
        # Note: assumes label differences don't matter for comparing dates

        # only a day-precision fully known undate can be equal to a datetime.date
        if isinstance(other, datetime.date):
            return self.earliest == other and self.latest == other

        other = self._comparison_type(other)
        if other is NotImplemented:
            return NotImplemented

        # check for apparent equality
        looks_equal = (
            self.earliest == other.earliest
            and self.latest == other.latest
            and self.initial_values == other.initial_values
        )
        # if everything looks the same, check for any unknowns in initial values
        # the same unknown date should NOT be considered equal
        # (but do we need a different equivalence check for this?)

        # NOTE: assumes that partially known values can only be written
        # in one format (i.e. X for missing digits).
        # If we support other formats, will need to normalize to common
        # internal format for comparison
        if looks_equal and any("X" in str(val) for val in self.initial_values.values()):
            return False

        return looks_equal

    def __lt__(self, other: object) -> bool:
        other = self._comparison_type(other)

        # if this date ends before the other date starts,
        # return true (this date is earlier, so it is less)
        if self.latest < other.earliest:
            return True

        # if the other one ends before this one starts,
        # return false (this date is later, so it is not less)
        if other.latest < self.earliest:
            return False

        # if it does not, check if one is included within the other
        # (e.g., single date within the same year)
        # comparison for those cases is not currently supported
        elif other in self or self in other:
            raise NotImplementedError(
                "Can't compare when one date falls within the other"
            )
        # NOTE: unsupported comparisons are supposed to return NotImplemented
        # However, doing that in this case results in a confusing TypeError!
        #   TypeError: '<' not supported between instances of 'Undate' and 'Undate'
        # How to handle when the comparison is ambiguous / indeterminate?
        # we may need a tribool / ternary type (true, false, unknown),
        # but not sure what python builtin methods will do with it (unknown = false?)

        # for any other case (i.e., self == other), return false
        return False

    def __gt__(self, other: object) -> bool:
        # define gt ourselves so we can support > comparison with datetime.date,
        # but rely on existing less than implementation.
        # strictly greater than must rule out equals
        return not (self < other or self == other)

    def __le__(self, other: object) -> bool:
        return self == other or self < other

    def __contains__(self, other: object) -> bool:
        # if the two dates are strictly equal, don't consider
        # either one as containing the other
        other = self._comparison_type(other)

        if self == other:
            return False

        return all(
            [
                self.earliest <= other.earliest,
                self.latest >= other.latest,
                # is precision sufficient for comparing partially known dates?
                # checking based on less precise /less granular time unit,
                # e.g. a day or month could be contained in a year
                # but not the reverse
                self.precision < other.precision,
            ]
        )

    @staticmethod
    def from_datetime_date(dt_date: datetime.date):
        """Initialize an :class:`Undate` object from a :class:`datetime.date`"""
        return Undate(dt_date.year, dt_date.month, dt_date.day)

    @property
    def known_year(self) -> bool:
        return self.is_known("year")

    def is_known(self, part: str) -> bool:
        """Check if a part of the date (year, month, day) is known.
        Returns False if unknown or only partially known."""
        # TODO: should we use constants or enum for values?

        # if we have an integer, then consider the date known
        # if we have a string, then it is only partially known; return false
        return isinstance(self.initial_values[part], int)

    def is_partially_known(self, part: str) -> bool:
        return isinstance(self.initial_values[part], str)

    @property
    def year(self) -> Optional[str]:
        "year as string (minimum 4 characters), if year is known"
        year = self._get_date_part("year")
        if year:
            return f"{year:>04}"
        # if value is unset but date precision is month or greater, return unknown month
        elif self.precision >= DatePrecision.YEAR:
            return self.MISSING_DIGIT * 4
        return None

    @property
    def month(self) -> Optional[str]:
        "month as 2-character string, or None if unknown/unset"
        # TODO: do we allow None for unknown month with day-level granularity?
        # TODO: need to distinguish between unknown (XX) and unset/not part of the date due to granularity
        month = self._get_date_part("month")
        if month:
            return f"{month:>02}"
        # if value is unset but date precision is month or greater, return unknown month
        elif self.precision >= DatePrecision.MONTH:
            return self.MISSING_DIGIT * 2
        return None

    @property
    def day(self) -> Optional[str]:
        "day as 2-character string or None if unset"
        day = self._get_date_part("day")
        if day:
            return f"{day:>02}"
        # if value is unset but date precision is day, return unknown day
        # (may not be possible to have day precision with day part set in normal use)
        elif self.precision == DatePrecision.DAY:
            return self.MISSING_DIGIT * 2
        return None

    def _get_date_part(self, part: str) -> Optional[str]:
        value = self.initial_values.get(part)
        return str(value) if value else None

    def duration(self) -> Timedelta:
        """What is the duration of this date?
        Calculate based on earliest and latest date within range,
        taking into account the precision of the date even if not all
        parts of the date are known."""

        # if precision is a single day, duration is one day
        # no matter when it is or what else is known
        if self.precision == DatePrecision.DAY:
            return ONE_DAY

        # if precision is month and year is unknown,
        # calculate month duration within a single year (not min/max)
        if self.precision == DatePrecision.MONTH:
            latest = self.latest
            if not self.known_year:
                # if year is unknown, calculate month duration in
                # a single year
                latest = Date(self.earliest.year, self.latest.month, self.latest.day)

                # latest = datetime.date(
                #     self.earliest.year, self.latest.month, self.latest.day
                # )
            delta = latest - self.earliest + ONE_DAY
            # month duration can't ever be more than 31 days
            # (could we ever know if it's smaller?)

            # if granularity == month but not known month, duration = 31
            if delta.astype(int) > 31:
                return ONE_MONTH_MAX
            return delta

        # otherwise, calculate based on earliest/latest range

        # subtract earliest from latest and add a day to count start day
        return self.latest - self.earliest + ONE_DAY

    def _missing_digit_minmax(
        self, value: str, min_val: int, max_val: int
    ) -> tuple[int, int]:
        # given a possible range, calculate min/max values for a string
        # with a missing digit

        # assuming two digit only (i.e., month or day)
        possible_values = [f"{n:02}" for n in range(min_val, max_val + 1)]
        # ensure input value has two digits
        value = "%02s" % value
        # generate regex where missing digit matches anything
        val_pattern = re.compile(value.replace(self.MISSING_DIGIT, "."))
        # identify all possible matches, then get min and max
        matches = [val for val in possible_values if val_pattern.match(val)]
        min_match = min(matches)
        max_match = max(matches)

        # split input string into a list so we can update individually
        new_min_val = list(value)
        new_max_val = list(value)
        for i, digit in enumerate(value):
            # replace the corresponding digit with our min and max
            if digit == self.MISSING_DIGIT:
                new_min_val[i] = min_match[i]
                new_max_val[i] = max_match[i]

        # combine the lists of digits back together and convert to int
        min_val = int("".join(new_min_val))
        max_val = int("".join(new_max_val))
        return (min_val, max_val)


class UndateInterval:
    """A date range between two uncertain dates.

    :param earliest: Earliest undate
    :type earliest: `undate.Undate`
    :param latest: Latest undate
    :type latest:  `undate.Undate`
    :param label: A string to label a specific undate interval, similar to labels of `undate.Undate`.
    :type label: `str`
    """

    # date range between two uncertain dates
    earliest: Union[Undate, None]
    latest: Union[Undate, None]
    label: Union[str, None]

    def __init__(
        self,
        earliest: Optional[Undate] = None,
        latest: Optional[Undate] = None,
        label: Optional[str] = None,
    ):
        # for now, assume takes two undate objects
        self.earliest = earliest
        self.latest = latest
        self.label = label

    def __str__(self) -> str:
        # using EDTF syntax for open ranges
        return "%s/%s" % (self.earliest or "..", self.latest or "")

    def format(self, format) -> str:
        """format this undate interval as a string using the specified format;
        for now, only supports named converters"""
        converter_cls = BaseDateConverter.available_converters().get(format, None)
        if converter_cls:
            return converter_cls().to_string(self)

        raise ValueError(f"Unsupported format '{format}'")

    def __repr__(self) -> str:
        if self.label:
            return "<UndateInterval '%s' (%s)>" % (self.label, self)
        return "<UndateInterval %s>" % self

    def __eq__(self, other) -> bool:
        # consider interval equal if both dates are equal
        return self.earliest == other.earliest and self.latest == other.latest

    def duration(self) -> Timedelta:
        """Calculate the duration between two undates.

        :returns: A duration
        :rtype: Timedelta
        """
        # what is the duration of this date range?

        # if range is open-ended, can't calculate
        if self.earliest is None or self.latest is None:
            return NotImplemented

        # if both years are known, subtract end of range from beginning of start
        if self.latest.known_year and self.earliest.known_year:
            return self.latest.latest - self.earliest.earliest + ONE_DAY

        # if neither year is known...
        elif not self.latest.known_year and not self.earliest.known_year:
            # under what circumstances can we assume that if both years
            # are unknown the dates are in the same year or sequential?
            duration = self.latest.earliest - self.earliest.earliest
            # if we get a negative, we've wrapped from end of one year
            # to the beginning of the next;
            # recalculate assuming second date is in the subsequent year
            if duration.days < 0:
                end = self.latest.earliest + ONE_YEAR
                duration = end - self.earliest.earliest

            # add the additional day *after* checking for a negative
            # or after recalculating with adjusted year
            duration += ONE_DAY

            return duration

        else:
            # is there any meaningful way to calculate duration
            # if one year is known and the other is not?
            raise NotImplementedError
