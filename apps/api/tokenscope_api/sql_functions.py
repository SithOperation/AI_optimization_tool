"""Stable ISO bucket strings across supported SQL dialects."""
from sqlalchemy import String
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class day_bucket(FunctionElement):
    type = String()
    inherit_cache = True


class hour_bucket(FunctionElement):
    type = String()
    inherit_cache = True


@compiles(day_bucket)
def day_default(element, compiler, **kw):
    return "date(%s)" % compiler.process(list(element.clauses)[0], **kw)


@compiles(day_bucket, "postgresql")
def day_postgresql(element, compiler, **kw):
    return "to_char(%s AT TIME ZONE 'UTC', 'YYYY-MM-DD')" % compiler.process(list(element.clauses)[0], **kw)


@compiles(hour_bucket)
def hour_default(element, compiler, **kw):
    return "strftime('%%H:00', %s)" % compiler.process(list(element.clauses)[0], **kw)


@compiles(hour_bucket, "postgresql")
def hour_postgresql(element, compiler, **kw):
    return "to_char(%s AT TIME ZONE 'UTC', 'HH24:00')" % compiler.process(list(element.clauses)[0], **kw)
