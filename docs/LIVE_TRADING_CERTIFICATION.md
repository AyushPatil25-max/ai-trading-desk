# Live Trading Certification & Environment Validation

## Overview
Phase 36 introduces the `LiveCertificationEngine`, ensuring absolute determinism and separation between configuration validation and live broker authorization.

## Core Principle: CERTIFICATION != AUTHORIZATION
Passing certification simply issues a `LiveReadinessMatrix`. It **never** arms live trading, **never** creates confirmation tokens, and **never** authorizes a broker order. It is purely an evaluative gate.

## LiveReadinessMatrix States
1. `NOT_CERTIFIED`: One or more blocking failures exist (e.g. Kill Switch active, bad config).
2. `CONDITIONALLY_CERTIFIED`: Partial clearance (unused in this phase).
3. `CERTIFIED_SANDBOX`: Fully cleared for PAPER, TEST, and SHADOW_LIVE environments.
4. `CERTIFIED_FOR_CONTROLLED_LIVE`: **Permanently unreachable in Phase 36.**

## Four Pillars of Validation
1. **Configuration**: Validates `LIVE_EXECUTION_ENABLED` is safely disabled.
2. **Safety**: Evaluates `kill_switch` state.
3. **Broker Connectivity**: Rejects all known production real-money URLs.
4. **Runtime Integrity**: Restricts `CONTROLLED_LIVE` and `PRODUCTION` environments.
