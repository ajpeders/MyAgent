"""Calendar service errors."""


class CalendarServiceError(Exception):
    pass


class EventNotFoundError(CalendarServiceError):
    pass
