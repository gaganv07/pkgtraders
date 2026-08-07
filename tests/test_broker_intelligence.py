"""
tests/test_broker_intelligence.py — Automated PyTest Test Suite
===============================================================
Verifies:
  1. Multi-broker symbol variant resolution across all 7 assets
  2. Execution filling mode adaptation
  3. Broker profile discovery
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath("."))

from app.broker_intelligence import BrokerIntelligenceEngine, BROKER_SYMBOL_PROFILES


def test_broker_intelligence_discovery():
    engine = BrokerIntelligenceEngine()
    profile = engine.discover_broker_environment()
    
    assert profile.company_name is not None
    assert len(profile.discovered_symbols) == 7
    assert "XAUUSD" in profile.discovered_symbols
    assert "BTCUSD" in profile.discovered_symbols
    assert "NAS100" in profile.discovered_symbols


def test_symbol_variant_resolution():
    engine = BrokerIntelligenceEngine()
    engine.discover_broker_environment()
    
    resolved_xau = engine.resolve_symbol("XAUUSD")
    resolved_btc = engine.resolve_symbol("BTCUSD")
    resolved_us30 = engine.resolve_symbol("US30")
    
    assert resolved_xau is not None
    assert resolved_btc is not None
    assert resolved_us30 is not None


def test_filling_mode_resolution():
    engine = BrokerIntelligenceEngine()
    engine.discover_broker_environment()
    
    fill_mode = engine.resolve_filling_mode("XAUUSD")
    assert fill_mode is not None
