"""Importing this module registers every model on Base.metadata.

Alembic and tests pull the metadata via ``from app.db.models import *`` so all
tables show up in autogenerate.
"""

from app.db.models.audit_models import (  # noqa: F401
    AuditFinding,
    AuditProgram,
    JETestRun,
    Sample,
    ThreeWayMatch,
    Workpaper,
)
from app.db.models.auth_models import (  # noqa: F401
    AuthToken,
    AuthTokenKind,
    Firm,
    User,
    UserRole,
    UserTweaks,
)
from app.db.models.bank import BankStatement, Reconciliation, ReconciliationKind  # noqa: F401
from app.db.models.books import (  # noqa: F401
    AccountType,
    ChartOfAccount,
    CoaMapping,
    GLEntry,
    TrialBalance,
)
from app.db.models.comparison_models import (  # noqa: F401
    ComparisonIssue,
    ComparisonRun,
    ComparisonStatus,
    Framework,
)
from app.db.models.engagement import (  # noqa: F401
    Client,
    Engagement,
    EngagementStatus,
    EngagementType,
)
from app.db.models.files import File, FileKind, ParsedStatus  # noqa: F401
from app.db.models.observability import AgentRun, AuditLog, QueryLog  # noqa: F401
from app.db.models.standards_ingest import StandardsIngestRun, StandardsIngestStatus  # noqa: F401
