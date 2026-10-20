"""
Import every model module here so Base.metadata knows about every
table regardless of which service's process calls init_db(). Each
service still only ever *writes* to the table(s) it owns - see the
top-level README's ownership map - but every service needs to know
the full schema so foreign keys resolve and so read-only lookups
(e.g. Sales service reading Customer) work.
"""
from common.models import master  # noqa: F401
from common.models import ledger  # noqa: F401
from common.models import business  # noqa: F401
from common.models import audit  # noqa: F401
