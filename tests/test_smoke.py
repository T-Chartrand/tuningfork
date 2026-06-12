"""Smoke tests: every rule's reference behavior, checked by a channel
that cannot share the author's failure mode (this test suite)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tuningfork import (CitationValidator, JsonBlockValidator, PathValidator,
                        Tier, ValidatorBank, GroundedAgent, assess)


def test_path_validator_catches_fabricated_path():
    v = PathValidator(evidence_paths=["/tmp/real.txt"], check_disk=False)
    out = "I read /tmp/real.txt and also /etc/made_up_config.yaml earlier."
    findings = v.run(out)
    by_claim = {f.claim: f.passed for f in findings}
    assert by_claim["/tmp/real.txt"] is True
    assert by_claim["/etc/made_up_config.yaml"] is False


def test_citation_validator_catches_phantom_citation():
    v = CitationValidator(valid_source_ids=["1", "2"])
    findings = v.run("Per [1] and [7], the API supports this.")
    fails = [f.claim for f in findings if not f.passed]
    assert fails == ["[7]"]


def test_json_validator():
    v = JsonBlockValidator()
    good = '```json\n{"a": 1}\n```'
    bad = '```json\n{"a": 1,}\n```'
    assert all(f.passed for f in v.run(good))
    assert any(not f.passed for f in v.run(bad))


def test_convenience_penalty_raises_tier():
    d = assess("This library has exactly what we need: v2.3.1 ships --auto-fix.")
    assert d.base_tier == Tier.MEDIUM          # catalog hits (version, flag)
    assert d.tier == Tier.HIGH                 # too-perfect -> raised
    assert d.perfection_hits


def test_tier_never_downgrades_for_destructive():
    d = assess("just explaining a concept", destructive=True)
    assert d.tier == Tier.HIGH


def test_harness_single_regeneration_cap():
    calls = {"n": 0}
    def liar(prompt: str) -> str:
        calls["n"] += 1
        return "See [9] for details."          # phantom citation every time
    bank = ValidatorBank([CitationValidator(valid_source_ids=["1"])])
    agent = GroundedAgent(liar, bank)
    result = agent.run("summarize source [1] v1.2")  # catalog -> MEDIUM
    assert calls["n"] == 2                      # exactly one regeneration
    assert result.regenerated and not result.trustworthy
    assert any("cap" in n for n in result.notes)


def test_harness_clean_pass_costs_one_call():
    def honest(prompt: str) -> str:
        return "See [1] for details."
    bank = ValidatorBank([CitationValidator(valid_source_ids=["1"])])
    result = GroundedAgent(honest, bank).run("summarize source [1] v1.2")
    assert result.trustworthy and not result.regenerated


def test_echo_validator_internal_repetition():
    from tuningfork import EchoValidator
    v = EchoValidator()
    out = ("The configuration lives in the main settings file. "
           "Some other sentence with enough length to count here. "
           "The configuration lives in the main settings file.")
    fails = [f for f in v.run(out) if not f.passed]
    assert len(fails) == 1 and "internal echo" in fails[0].evidence


def test_echo_validator_stale_reassertion():
    from tuningfork import EchoValidator
    rejected = "Per source nine, the settings live in the secret config file."
    v = EchoValidator(rejected_history=[rejected])
    out = "Per source nine, the settings live in the secret config file."
    fails = [f for f in v.run(out) if not f.passed]
    assert len(fails) == 1
    assert "stale echo" in fails[0].evidence and fails[0].severity == "high"


def test_echo_validator_clean_output_passes():
    from tuningfork import EchoValidator
    v = EchoValidator()
    out = ("The first sentence says one particular thing here. "
           "The second sentence says something entirely different.")
    assert all(f.passed for f in v.run(out))


def test_ledger_builds_known_signatures_from_recurrence():
    from tuningfork import (CitationValidator, RejectionLedger, ValidatorBank,
                            EchoValidator)
    bank = ValidatorBank([CitationValidator(valid_source_ids=["1"])])
    ledger = RejectionLedger(recurrence_threshold=2)
    out = "Per [9], the flag exists and this is certainly documented somewhere."
    for _ in range(2):                       # same fabrication, twice
        report = bank.run(out)
        ledger.record(out, report)
    assert "[9]" in ledger.known_signatures()          # graduated to 'known'
    prof = ledger.profile()
    assert prof.total_rejections == 2
    assert prof.rejections_by_validator["citation"] == 2
    # ledger feeds echo detection: re-asserting the mined fabrication
    echo = EchoValidator(rejected_history=ledger.rejected_outputs)
    fails = [f for f in echo.run(out) if not f.passed]
    assert fails and fails[0].severity == "high"


def test_ledger_ignores_clean_reports():
    from tuningfork import CitationValidator, RejectionLedger, ValidatorBank
    bank = ValidatorBank([CitationValidator(valid_source_ids=["1"])])
    ledger = RejectionLedger()
    report = bank.run("Per [1], all good.")
    ledger.record("Per [1], all good.", report)
    assert ledger.profile().total_rejections == 0
    assert ledger.known_signatures() == []
