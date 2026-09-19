"""
test_introspection_engine.py
=============================
Comprehensive pytest suite for Part B — Runtime Introspection Engine.

Coverage
--------
TestSubsystemInterface      — IntrospectableSubsystem + NullSubsystem
TestSubsystemRegistry       — SubsystemRegistry CRUD and iteration
TestRuntimeSnapshot         — RuntimeSnapshot immutability and accessors
TestSnapshotBuilder         — SnapshotBuilder aggregation and edge cases
TestIntrospectionEngine     — IntrospectionEngine full pipeline

All tests use stdlib only — no network calls, no I/O.
"""

import pytest
from runtime.introspection.subsystem_interface import (
    IntrospectableSubsystem,
    SubsystemStatus,
    HealthStatus,
    SubsystemHealth,
    NullSubsystem,
)
from runtime.introspection.subsystem_registry import SubsystemRegistry
from runtime.introspection.runtime_snapshot import (
    RuntimeSnapshot,
    AggregatedHealth,
    make_empty_snapshot,
)
from runtime.introspection.snapshot_builder import SnapshotBuilder, SnapshotBuilderConfig
from runtime.introspection.introspection_engine import IntrospectionEngine


# ============================================================
# Concrete subsystem implementations for testing
# ============================================================

class OnlineSubsystem(IntrospectableSubsystem):
    def status(self): return SubsystemStatus.ONLINE
    def health(self): return SubsystemHealth(status=HealthStatus.HEALTHY, checks_passed=3, checks_total=3)
    def capabilities(self): return ["cap_a", "cap_b"]
    def limitations(self): return ["limit_x"]
    def diagnostics(self): return {"uptime_s": 120, "requests": 5}


class DegradedSubsystem(IntrospectableSubsystem):
    def status(self): return SubsystemStatus.DEGRADED
    def health(self): return SubsystemHealth(status=HealthStatus.WARNING, issues=["Slow response"])
    def capabilities(self): return ["cap_c"]
    def limitations(self): return ["limit_y", "limit_z"]
    def diagnostics(self): return {"mode": "degraded"}


class OfflineSubsystem(IntrospectableSubsystem):
    def status(self): return SubsystemStatus.OFFLINE
    def health(self): return SubsystemHealth(status=HealthStatus.CRITICAL, issues=["Connection lost"])
    def capabilities(self): return []
    def limitations(self): return ["Not operational"]
    def diagnostics(self): return {}


class BrokenSubsystem(IntrospectableSubsystem):
    """Raises on every method call to test defensive builder behaviour."""
    def status(self): raise RuntimeError("status exploded")
    def health(self): raise RuntimeError("health exploded")
    def capabilities(self): raise RuntimeError("caps exploded")
    def limitations(self): raise RuntimeError("limits exploded")
    def diagnostics(self): raise RuntimeError("diagnostics exploded")


class BrainSubsystem(IntrospectableSubsystem):
    """Name contains 'brain' — builder should classify under brains."""
    def status(self): return SubsystemStatus.ONLINE
    def health(self): return SubsystemHealth(status=HealthStatus.HEALTHY)
    def capabilities(self): return ["LLM inference"]
    def limitations(self): return ["Requires API key"]
    def diagnostics(self): return {}
    def subsystem_name(self): return "cloud_brain"


class MemorySubsystem(IntrospectableSubsystem):
    """Name contains 'memory' — builder should classify under memory."""
    def status(self): return SubsystemStatus.ONLINE
    def health(self): return SubsystemHealth(status=HealthStatus.HEALTHY)
    def capabilities(self): return ["Store context"]
    def limitations(self): return ["In-memory only"]
    def diagnostics(self): return {}
    def subsystem_name(self): return "working_memory"


# ============================================================
# TestSubsystemInterface
# ============================================================

class TestSubsystemInterface:

    def test_online_status(self):
        s = OnlineSubsystem()
        assert s.status() == SubsystemStatus.ONLINE

    def test_health_healthy(self):
        s = OnlineSubsystem()
        h = s.health()
        assert h.status == HealthStatus.HEALTHY
        assert h.checks_passed == 3
        assert h.checks_total == 3

    def test_capabilities_list(self):
        s = OnlineSubsystem()
        caps = s.capabilities()
        assert isinstance(caps, list)
        assert "cap_a" in caps

    def test_limitations_list(self):
        s = OnlineSubsystem()
        lims = s.limitations()
        assert isinstance(lims, list)
        assert "limit_x" in lims

    def test_diagnostics_dict(self):
        s = OnlineSubsystem()
        d = s.diagnostics()
        assert isinstance(d, dict)
        assert "uptime_s" in d

    def test_subsystem_name_default_is_class_name(self):
        s = OnlineSubsystem()
        assert s.subsystem_name() == "OnlineSubsystem"

    def test_null_subsystem_offline(self):
        n = NullSubsystem()
        assert n.status() == SubsystemStatus.OFFLINE

    def test_null_subsystem_unknown_health(self):
        n = NullSubsystem()
        assert n.health().status == HealthStatus.UNKNOWN

    def test_null_subsystem_no_capabilities(self):
        n = NullSubsystem()
        assert n.capabilities() == []

    def test_null_subsystem_custom_name(self):
        n = NullSubsystem(name="placeholder_module")
        assert n.subsystem_name() == "placeholder_module"

    def test_null_subsystem_diagnostics_has_operational_false(self):
        n = NullSubsystem()
        d = n.diagnostics()
        assert d.get("operational") is False

    def test_health_to_dict(self):
        h = SubsystemHealth(
            status=HealthStatus.WARNING,
            issues=["slow"],
            checks_passed=2,
            checks_total=3,
            notes=["note1"],
        )
        d = h.to_dict()
        assert d["status"] == "warning"
        assert d["issues"] == ["slow"]
        assert d["checks_passed"] == 2
        assert d["notes"] == ["note1"]

    def test_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            IntrospectableSubsystem()  # type: ignore


# ============================================================
# TestSubsystemRegistry
# ============================================================

class TestSubsystemRegistry:

    def test_register_and_get(self):
        reg = SubsystemRegistry()
        reg.register("alpha", OnlineSubsystem())
        assert reg.get("alpha") is not None

    def test_get_unknown_returns_none(self):
        reg = SubsystemRegistry()
        assert reg.get("ghost") is None

    def test_require_known(self):
        reg = SubsystemRegistry()
        s = OnlineSubsystem()
        reg.register("alpha", s)
        assert reg.require("alpha") is s

    def test_require_unknown_raises(self):
        reg = SubsystemRegistry()
        with pytest.raises(KeyError):
            reg.require("ghost")

    def test_empty_name_raises(self):
        reg = SubsystemRegistry()
        with pytest.raises(ValueError):
            reg.register("", OnlineSubsystem())

    def test_whitespace_name_raises(self):
        reg = SubsystemRegistry()
        with pytest.raises(ValueError):
            reg.register("   ", OnlineSubsystem())

    def test_wrong_type_raises(self):
        reg = SubsystemRegistry()
        with pytest.raises(TypeError):
            reg.register("bad", "not a subsystem")  # type: ignore

    def test_duplicate_name_replaces(self):
        reg = SubsystemRegistry()
        s1 = OnlineSubsystem()
        s2 = DegradedSubsystem()
        reg.register("x", s1)
        reg.register("x", s2)
        assert reg.get("x") is s2

    def test_unregister_existing(self):
        reg = SubsystemRegistry()
        reg.register("alpha", OnlineSubsystem())
        result = reg.unregister("alpha")
        assert result is True
        assert reg.get("alpha") is None

    def test_unregister_nonexistent_returns_false(self):
        reg = SubsystemRegistry()
        assert reg.unregister("ghost") is False

    def test_names_order_preserved(self):
        reg = SubsystemRegistry()
        reg.register("c", OnlineSubsystem())
        reg.register("a", OnlineSubsystem())
        reg.register("b", OnlineSubsystem())
        assert reg.names() == ["c", "a", "b"]

    def test_items_iteration(self):
        reg = SubsystemRegistry()
        reg.register("x", OnlineSubsystem())
        reg.register("y", DegradedSubsystem())
        pairs = list(reg.items())
        assert len(pairs) == 2
        assert pairs[0][0] == "x"

    def test_all_subsystems(self):
        reg = SubsystemRegistry()
        reg.register("a", OnlineSubsystem())
        subs = reg.all_subsystems()
        assert len(subs) == 1

    def test_len(self):
        reg = SubsystemRegistry()
        reg.register("a", OnlineSubsystem())
        reg.register("b", DegradedSubsystem())
        assert len(reg) == 2

    def test_contains(self):
        reg = SubsystemRegistry()
        reg.register("alpha", OnlineSubsystem())
        assert "alpha" in reg
        assert "beta" not in reg

    def test_is_empty_true(self):
        reg = SubsystemRegistry()
        assert reg.is_empty() is True

    def test_is_empty_false_after_register(self):
        reg = SubsystemRegistry()
        reg.register("x", OnlineSubsystem())
        assert reg.is_empty() is False

    def test_clear(self):
        reg = SubsystemRegistry()
        reg.register("a", OnlineSubsystem())
        reg.clear()
        assert reg.is_empty() is True

    def test_repr_contains_count(self):
        reg = SubsystemRegistry()
        reg.register("x", OnlineSubsystem())
        assert "1 subsystems" in repr(reg)



# ============================================================
# TestRuntimeSnapshot
# ============================================================

class TestRuntimeSnapshot:

    def _make_health(self, overall="healthy"):
        return AggregatedHealth(
            overall=overall,
            healthy_count=2,
            warning_count=0,
            critical_count=0,
            unknown_count=0,
            total_subsystems=2,
            issues=(),
        )

    def _make_snapshot(self, **overrides):
        defaults = dict(
            snapshot_id="abc123",
            taken_at="2026-08-02T00:00:00+00:00",
            identity_name="AG",
            identity_version="2.0.0",
            loaded_modules=("cloud_brain", "introspection"),
            connected_subsystems=("alpha",),
            disconnected_subsystems=(),
            brains={"cloud_brain": "online"},
            memory={"working_memory": "online"},
            runtime_health=self._make_health(),
            capabilities=("cap_a", "cap_b"),
            limitations=("limit_x",),
            configuration={"env": "test"},
            diagnostics={"alpha": {"status": "online"}},
            subsystem_count=1,
        )
        defaults.update(overrides)
        return RuntimeSnapshot(**defaults)

    def test_snapshot_is_immutable(self):
        snap = self._make_snapshot()
        with pytest.raises((AttributeError, TypeError)):
            snap.identity_name = "Changed"  # type: ignore

    def test_is_healthy_true(self):
        snap = self._make_snapshot()
        assert snap.is_healthy is True

    def test_is_healthy_false(self):
        snap = self._make_snapshot(runtime_health=self._make_health("critical"))
        assert snap.is_healthy is False

    def test_has_disconnected_false(self):
        snap = self._make_snapshot()
        assert snap.has_disconnected is False

    def test_has_disconnected_true(self):
        snap = self._make_snapshot(disconnected_subsystems=("beta",))
        assert snap.has_disconnected is True

    def test_online_count(self):
        snap = self._make_snapshot(connected_subsystems=("a", "b", "c"))
        assert snap.online_count == 3

    def test_offline_count(self):
        snap = self._make_snapshot(disconnected_subsystems=("x", "y"))
        assert snap.offline_count == 2

    def test_to_dict_keys(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        for key in ("snapshot_id", "taken_at", "identity", "loaded_modules",
                    "connected_subsystems", "disconnected_subsystems",
                    "brains", "memory", "runtime_health", "capabilities",
                    "limitations", "configuration", "diagnostics", "subsystem_count"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_identity(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert d["identity"]["name"] == "AG"
        assert d["identity"]["version"] == "2.0.0"

    def test_to_dict_lists_not_tuples(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert isinstance(d["loaded_modules"], list)
        assert isinstance(d["capabilities"], list)
        assert isinstance(d["limitations"], list)

    def test_make_empty_snapshot(self):
        snap = make_empty_snapshot()
        assert snap.identity_name == "AG"
        assert snap.subsystem_count == 0
        assert snap.runtime_health.overall == "unknown"
        assert snap.is_healthy is False

    def test_make_empty_snapshot_custom_identity(self):
        snap = make_empty_snapshot(identity_name="TestBot", identity_version="9.9.9")
        assert snap.identity_name == "TestBot"
        assert snap.identity_version == "9.9.9"

    def test_aggregated_health_to_dict(self):
        h = self._make_health("warning")
        d = h.to_dict()
        assert d["overall"] == "warning"
        assert "healthy_count" in d
        assert "issues" in d



# ============================================================
# TestSnapshotBuilder
# ============================================================

class TestSnapshotBuilder:

    def _make_registry(self, *pairs):
        reg = SubsystemRegistry()
        for name, sub in pairs:
            reg.register(name, sub)
        return reg

    def test_empty_registry_produces_snapshot(self):
        reg = SubsystemRegistry()
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert isinstance(snap, RuntimeSnapshot)
        assert snap.subsystem_count == 0

    def test_online_subsystem_in_connected(self):
        reg = self._make_registry(("alpha", OnlineSubsystem()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert "alpha" in snap.connected_subsystems
        assert "alpha" not in snap.disconnected_subsystems

    def test_offline_subsystem_in_disconnected(self):
        reg = self._make_registry(("beta", OfflineSubsystem()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert "beta" in snap.disconnected_subsystems

    def test_degraded_subsystem_in_disconnected(self):
        reg = self._make_registry(("gamma", DegradedSubsystem()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert "gamma" in snap.disconnected_subsystems

    def test_capabilities_aggregated(self):
        reg = self._make_registry(
            ("s1", OnlineSubsystem()),   # cap_a, cap_b
            ("s2", DegradedSubsystem()), # cap_c
        )
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert "cap_a" in snap.capabilities
        assert "cap_b" in snap.capabilities
        assert "cap_c" in snap.capabilities

    def test_capabilities_deduplicated(self):
        class SameCaps(IntrospectableSubsystem):
            def status(self): return SubsystemStatus.ONLINE
            def health(self): return SubsystemHealth(status=HealthStatus.HEALTHY)
            def capabilities(self): return ["shared_cap"]
            def limitations(self): return []
            def diagnostics(self): return {}

        reg = self._make_registry(("a", SameCaps()), ("b", SameCaps()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert snap.capabilities.count("shared_cap") == 1

    def test_limitations_aggregated(self):
        reg = self._make_registry(
            ("s1", OnlineSubsystem()),   # limit_x
            ("s2", DegradedSubsystem()), # limit_y, limit_z
        )
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert "limit_x" in snap.limitations
        assert "limit_y" in snap.limitations

    def test_health_all_healthy(self):
        reg = self._make_registry(
            ("a", OnlineSubsystem()),
            ("b", OnlineSubsystem()),
        )
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert snap.runtime_health.overall == "healthy"

    def test_health_warning_when_one_degraded(self):
        reg = self._make_registry(
            ("a", OnlineSubsystem()),
            ("b", DegradedSubsystem()),
        )
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert snap.runtime_health.overall == "warning"

    def test_health_critical_when_one_offline(self):
        reg = self._make_registry(
            ("a", OnlineSubsystem()),
            ("b", OfflineSubsystem()),
        )
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert snap.runtime_health.overall == "critical"

    def test_issues_collected(self):
        reg = self._make_registry(("b", OfflineSubsystem()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert len(snap.runtime_health.issues) > 0
        assert any("Connection lost" in i for i in snap.runtime_health.issues)

    def test_broken_subsystem_does_not_crash_builder(self):
        reg = self._make_registry(("bad", BrokenSubsystem()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert isinstance(snap, RuntimeSnapshot)

    def test_diagnostics_per_subsystem(self):
        reg = self._make_registry(("alpha", OnlineSubsystem()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert "alpha" in snap.diagnostics

    def test_brain_classified(self):
        reg = self._make_registry(("cloud_brain", BrainSubsystem()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert "cloud_brain" in snap.brains

    def test_memory_classified(self):
        reg = self._make_registry(("working_memory", MemorySubsystem()))
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert "working_memory" in snap.memory

    def test_identity_from_config(self):
        config = SnapshotBuilderConfig(identity_name="TestAG", identity_version="3.1.4")
        builder = SnapshotBuilder(config=config)
        snap = builder.build(SubsystemRegistry())
        assert snap.identity_name == "TestAG"
        assert snap.identity_version == "3.1.4"

    def test_configuration_summary_in_snapshot(self):
        config = SnapshotBuilderConfig(configuration_summary={"env": "prod", "debug": False})
        builder = SnapshotBuilder(config=config)
        snap = builder.build(SubsystemRegistry())
        assert snap.configuration["env"] == "prod"
        assert snap.configuration["debug"] is False

    def test_snapshot_id_unique_each_build(self):
        builder = SnapshotBuilder()
        reg = SubsystemRegistry()
        s1 = builder.build(reg)
        s2 = builder.build(reg)
        assert s1.snapshot_id != s2.snapshot_id

    def test_module_prefix_filter(self):
        config = SnapshotBuilderConfig(module_prefix_filter="introspection")
        builder = SnapshotBuilder(config=config)
        snap = builder.build(SubsystemRegistry())
        # All listed modules should start with 'introspection'
        for mod in snap.loaded_modules:
            assert mod.startswith("introspection"), f"Unexpected module: {mod}"

    def test_no_filter_includes_more_modules(self):
        config_filtered = SnapshotBuilderConfig(module_prefix_filter="introspection")
        config_unfiltered = SnapshotBuilderConfig(module_prefix_filter="")
        builder_f = SnapshotBuilder(config=config_filtered)
        builder_u = SnapshotBuilder(config=config_unfiltered)
        reg = SubsystemRegistry()
        snap_f = builder_f.build(reg)
        snap_u = builder_u.build(reg)
        assert len(snap_u.loaded_modules) >= len(snap_f.loaded_modules)

    def test_subsystem_count_correct(self):
        reg = self._make_registry(
            ("a", OnlineSubsystem()),
            ("b", DegradedSubsystem()),
            ("c", OfflineSubsystem()),
        )
        builder = SnapshotBuilder()
        snap = builder.build(reg)
        assert snap.subsystem_count == 3


# ============================================================
# TestIntrospectionEngine
# ============================================================

class TestIntrospectionEngine:

    def test_build_snapshot_returns_runtime_snapshot(self):
        engine = IntrospectionEngine()
        snap = engine.build_snapshot()
        assert isinstance(snap, RuntimeSnapshot)

    def test_empty_engine_snapshot(self):
        engine = IntrospectionEngine()
        snap = engine.build_snapshot()
        assert snap.subsystem_count == 0
        assert snap.online_count == 0

    def test_register_then_snapshot(self):
        engine = IntrospectionEngine()
        engine.register("alpha", OnlineSubsystem())
        snap = engine.build_snapshot()
        assert "alpha" in snap.connected_subsystems

    def test_unregister_removes_from_snapshot(self):
        engine = IntrospectionEngine()
        engine.register("alpha", OnlineSubsystem())
        engine.unregister("alpha")
        snap = engine.build_snapshot()
        assert "alpha" not in snap.connected_subsystems

    def test_unregister_nonexistent_returns_false(self):
        engine = IntrospectionEngine()
        assert engine.unregister("ghost") is False

    def test_last_snapshot_none_before_build(self):
        engine = IntrospectionEngine()
        assert engine.last_snapshot is None

    def test_last_snapshot_set_after_build(self):
        engine = IntrospectionEngine()
        engine.build_snapshot()
        assert engine.last_snapshot is not None

    def test_last_snapshot_updated_on_rebuild(self):
        engine = IntrospectionEngine()
        s1 = engine.build_snapshot()
        engine.register("new", OnlineSubsystem())
        s2 = engine.build_snapshot()
        assert s1.snapshot_id != s2.snapshot_id
        assert engine.last_snapshot.snapshot_id == s2.snapshot_id

    def test_cache_disabled(self):
        engine = IntrospectionEngine(cache_last=False)
        engine.build_snapshot()
        assert engine.last_snapshot is None

    def test_registry_accessor(self):
        engine = IntrospectionEngine()
        assert isinstance(engine.registry, SubsystemRegistry)

    def test_subsystem_count(self):
        engine = IntrospectionEngine()
        engine.register("a", OnlineSubsystem())
        engine.register("b", DegradedSubsystem())
        assert engine.subsystem_count() == 2

    def test_registered_subsystem_names(self):
        engine = IntrospectionEngine()
        engine.register("x", OnlineSubsystem())
        engine.register("y", OfflineSubsystem())
        names = engine.registered_subsystem_names()
        assert "x" in names
        assert "y" in names

    def test_snapshot_summary_empty_before_build(self):
        engine = IntrospectionEngine()
        assert engine.snapshot_summary() == {}

    def test_snapshot_summary_after_build(self):
        engine = IntrospectionEngine()
        engine.register("alpha", OnlineSubsystem())
        engine.build_snapshot()
        summary = engine.snapshot_summary()
        assert "snapshot_id" in summary
        assert "overall_health" in summary
        assert "subsystem_count" in summary
        assert summary["subsystem_count"] == 1

    def test_broken_subsystem_does_not_crash_engine(self):
        engine = IntrospectionEngine()
        engine.register("broken", BrokenSubsystem())
        snap = engine.build_snapshot()
        assert isinstance(snap, RuntimeSnapshot)

    def test_custom_registry_injected(self):
        reg = SubsystemRegistry()
        reg.register("injected", OnlineSubsystem())
        engine = IntrospectionEngine(registry=reg)
        snap = engine.build_snapshot()
        assert "injected" in snap.connected_subsystems

    def test_custom_builder_config(self):
        config = SnapshotBuilderConfig(identity_name="CustomAG", identity_version="5.0.0")
        engine = IntrospectionEngine(builder_config=config)
        snap = engine.build_snapshot()
        assert snap.identity_name == "CustomAG"
        assert snap.identity_version == "5.0.0"

    def test_multiple_snapshots_independent(self):
        engine = IntrospectionEngine()
        engine.register("a", OnlineSubsystem())
        s1 = engine.build_snapshot()
        engine.register("b", OfflineSubsystem())
        s2 = engine.build_snapshot()
        # s1 should not contain "b"
        assert "b" not in s1.disconnected_subsystems
        assert "b" in s2.disconnected_subsystems

    def test_health_reflected_in_snapshot(self):
        engine = IntrospectionEngine()
        engine.register("good", OnlineSubsystem())
        engine.register("bad", OfflineSubsystem())
        snap = engine.build_snapshot()
        assert snap.runtime_health.overall == "critical"

    def test_snapshot_immutable_after_engine_mutation(self):
        engine = IntrospectionEngine()
        engine.register("a", OnlineSubsystem())
        snap = engine.build_snapshot()
        engine.register("b", OfflineSubsystem())
        # Existing snapshot should not change
        assert "b" not in snap.disconnected_subsystems
