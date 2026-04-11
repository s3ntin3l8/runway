"""
Unit tests for CollectorManager.

Tests cover:
- Lazy loading of collectors
- Keychain warmup logic (macOS specific)
- Collection orchestration and flattening
- Global timeout handling
"""

import pytest
import asyncio
import platform
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.services.collector_manager import CollectorManager
from app.core.config import settings


@pytest.fixture
def manager():
    """Create a CollectorManager instance."""
    return CollectorManager()


class TestCollectorManagerInitialization:
    """Test initialization and lazy loading."""

    def test_init_config_count(self, manager):
        """Test that manager initializes with correct number of configs."""
        # Check that we have at least some collectors defined
        assert len(manager.collector_configs) > 0
        assert manager.smart_collectors == []
        assert manager._keychain_warmed_up is False

    def test_lazy_load_collectors(self, manager):
        """Test that collectors are only instantiated when needed."""
        manager._lazy_load_collectors()
        assert len(manager.smart_collectors) == len(manager.collector_configs)
        
        # Second call should not re-instantiate
        first_list = manager.smart_collectors
        manager._lazy_load_collectors()
        assert manager.smart_collectors is first_list


class TestCollectorManagerWarmup:
    """Test keychain warmup logic."""

    @pytest.mark.asyncio
    async def test_warmup_keychain_non_darwin(self, manager):
        """Test that warmup is skipped on non-macOS platforms."""
        with patch("platform.system", return_value="Linux"):
            await manager._warmup_keychain()
            assert manager._keychain_warmed_up is True

    @pytest.mark.asyncio
    async def test_warmup_keychain_disabled(self, manager):
        """Test that warmup is skipped if disabled in settings."""
        with patch("platform.system", return_value="Darwin"):
            with patch.object(settings, "LOCAL_CREDENTIAL_SCRAPING_ENABLED", False):
                await manager._warmup_keychain()
                assert manager._keychain_warmed_up is True

    @pytest.mark.asyncio
    async def test_warmup_keychain_already_warmed(self, manager):
        """Test that warmup only runs once."""
        manager._keychain_warmed_up = True
        with patch("platform.system", return_value="Darwin") as mock_system:
            await manager._warmup_keychain()
            mock_system.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.collector_manager.os.getenv")
    @patch("app.core.keychain.get_keychain_secret")
    async def test_warmup_keychain_darwin_enabled(self, mock_get_secret, mock_getenv, manager):
        """Test warmup logic on macOS with all triggers."""
        # Setup: Mock environment to trigger all keychain prompts
        mock_getenv.return_value = None # Nothing in env
        
        with patch("platform.system", return_value="Darwin"):
            with patch.object(settings, "LOCAL_CREDENTIAL_SCRAPING_ENABLED", True):
                await manager._warmup_keychain()
                
                assert manager._keychain_warmed_up is True
                # Should have called get_keychain_secret for Claude and Chrome
                assert mock_get_secret.call_count >= 2
                
    @pytest.mark.asyncio
    @patch("app.services.collector_manager.os.getenv")
    @patch("app.core.keychain.get_keychain_secret")
    async def test_warmup_keychain_skip_if_env_set(self, mock_get_secret, mock_getenv, manager):
        """Test that warmup skips secrets already in environment."""
        # Setup: Mock environment to have all secrets
        mock_getenv.return_value = "already-set"
        
        with patch("platform.system", return_value="Darwin"):
            with patch.object(settings, "LOCAL_CREDENTIAL_SCRAPING_ENABLED", True):
                await manager._warmup_keychain()
                
                assert manager._keychain_warmed_up is True
                # Should NOT have called get_keychain_secret
                mock_get_secret.assert_not_called()


class TestCollectorManagerCollection:
    """Test the main collect_all orchestration."""

    @pytest.mark.asyncio
    async def test_collect_all_success(self, manager):
        """Test successful collection from multiple sources."""
        # Mock SmartCollectors
        mock_smart1 = AsyncMock()
        mock_smart1.collect.return_value = [{"service": "S1", "remaining": "100%"}]
        mock_smart1.collector_name = "C1"
        
        mock_smart2 = AsyncMock()
        mock_smart2.collect.return_value = [{"service": "S2", "remaining": "50%"}]
        mock_smart2.collector_name = "C2"
        
        manager.smart_collectors = [mock_smart1, mock_smart2]
        
        # Mock external metrics
        with patch("app.services.collector_manager.external_metric_service.get_all_metrics", new_callable=AsyncMock) as mock_external:
            mock_external.return_value = [{"service": "Ext", "remaining": "OK"}]
            
            # Run collection
            results = await manager.collect_all()
            
            assert len(results) == 3
            services = [r["service"] for r in results]
            assert "S1" in services
            assert "S2" in services
            assert "Ext" in services

    @pytest.mark.asyncio
    async def test_collect_all_timeout(self, manager):
        """Test that global timeout is handled gracefully."""
        # Mock a slow collector
        async def slow_collect(*args, **kwargs):
            await asyncio.sleep(0.5)
            return []
            
        mock_smart = AsyncMock()
        mock_smart.collect.side_effect = slow_collect
        mock_smart.collector_name = "Slow"
        
        manager.smart_collectors = [mock_smart]
        
        # Run with very short timeout
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            results = await manager.collect_all()
            assert results == [] # Should return empty list on global timeout (external metrics skipped too in this implementation)

    @pytest.mark.asyncio
    async def test_collect_all_handles_exceptions(self, manager):
        """Test that exceptions in one collector don't crash everything."""
        # Although SmartCollector handles most exceptions, collect_all has safety too
        mock_smart1 = AsyncMock()
        mock_smart1.collect.return_value = [{"service": "OK"}]
        
        mock_smart2 = AsyncMock()
        # Simulate an unexpected exception that escapes SmartCollector.collect
        mock_smart2.collect.side_effect = Exception("Unexpected failure")
        mock_smart2.collector_name = "Failing"
        
        manager.smart_collectors = [mock_smart1, mock_smart2]
        
        with patch("app.services.collector_manager.external_metric_service.get_all_metrics", new_callable=AsyncMock) as mock_ext:
            mock_ext.return_value = []
            
            # Using gather with return_exceptions=True
            results = await manager.collect_all()
            
            # Should have the one successful result
            assert len(results) == 1
            assert results[0]["service"] == "OK"
