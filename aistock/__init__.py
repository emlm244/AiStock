"""
Aistock Robot core package.

The legacy implementation in this repository depended on a large stack of
third‑party libraries (pandas, numpy, ibapi, sklearn, …) that are unavailable in
the execution environment and were tightly coupled to Interactive Brokers.
To regain testability and provide a safe baseline, the core runtime has been
rewritten around lightweight, deterministic primitives that rely only on the
Python standard library.

Modules are intentionally small and composable so they can be audited, tested,
and extended without reintroducing the previous complexity.
"""

from .acquisition import (  # noqa: F401
    AcquisitionReport,
    DataAcquisitionConfig,
    DataAcquisitionService,
    FetchedArtifact,
    FileSystemSourceConfig,
    ValidationReport,
)
from .agent import AdaptiveAgent, AssetClassPolicy, ObjectiveThresholds  # noqa: F401
from .audit import AlertDispatcher, AuditConfig, AuditLogger, ComplianceReporter, StateStore  # noqa: F401
from .automation import (  # noqa: F401
    AutoCalibrationConfig,
    AutoPilot,
    AutoPilotReport,
    AutoTrainingConfig,
    PipelineConfig,
)
from .calibration import CalibrationSummary, calibrate_objectives  # noqa: F401
from .config import (  # noqa: F401
    BacktestConfig,
    BrokerConfig,
    ContractSpec,
    DataSource,
    EngineConfig,
    ExecutionConfig,
    RiskLimits,
    RunMode,
    UniverseConfig,
)
from .data import Bar, load_csv_directory  # noqa: F401
from .engine import BacktestResult, BacktestRunner  # noqa: F401
from .brokers.base import BaseBroker  # noqa: F401
from .brokers.paper import PaperBroker  # noqa: F401
from .brokers.management import (  # noqa: F401
    AllocationResult,
    BrokerReconciliationReport,
    BrokerReconciliationService,
    CapitalAllocationEngine,
    ContractRegistry,
    PositionDrift,
)
from .ingestion import DataIngestionConfig, DataIngestionService, IngestionReport  # noqa: F401
from .promotion import ModelPromotionService, PromotionConfig, PromotionDecision, PromotionPolicy  # noqa: F401
from .portfolio import Portfolio, Position  # noqa: F401
from .risk import RiskEngine  # noqa: F401
from .universe import UniverseSelectionResult, UniverseSelector  # noqa: F401
from .supervision import (  # noqa: F401
    AlertLevel,
    AlertManager,
    ApprovalAction,
    ApprovalGate,
    ApprovalRequest,
    HealthMonitor,
    ScheduledAutopilot,
    SupervisedAutopilot,
    SupervisionConfig,
)
from .headless import (  # noqa: F401
    AdaptiveRiskManager,
    AutoPromotionValidator,
    ErrorRecoverySystem,
    HeadlessAutopilot,
    HeadlessConfig,
    RemoteKillSwitch,
)
from .fsd import (  # noqa: F401
    ConfidenceScorer,
    FSDConfig,
    FSDEngine,
    ReinforcementLearner,
    Trade,
)
