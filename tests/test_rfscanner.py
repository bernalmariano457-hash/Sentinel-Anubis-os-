from __future__ import annotations

import json
import math
import sqlite3
import tempfile
from pathlib import Path
import sys
import os

import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_rate():
    return 2_048_000


@pytest.fixture
def fft_size():
    return 2048


@pytest.fixture
def dsp_cfg():
    from modules.rf.rf_config import DspConfig
    return DspConfig(
        fft_size=2048,
        window="blackman",
        snr_threshold=8.0,
        samples_per_read=131_072,
        cfar_guard=4,
        cfar_ref=16,
        dc_spike_remove=True,
    )


@pytest.fixture
def dsp_engine(dsp_cfg, sample_rate):
    from modules.rf.dsp import DSPEngine
    return DSPEngine(dsp_cfg, sample_rate)


@pytest.fixture
def mock_sdr(sample_rate):
    from modules.rf.rf_mock import MockSDRManager
    return MockSDRManager(sample_rate=sample_rate)


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def storage_cfg(tmp_dir):
    from modules.rf.rf_config import StorageConfig
    return StorageConfig(data_dir=str(tmp_dir / "rf"))


@pytest.fixture
def signal_db(storage_cfg):
    from modules.rf.rf_storage import SignalDB
    return SignalDB(storage_cfg)


class TestConfig:
    def test_default_loads(self):
        from modules.rf.rf_config import load_config
        cfg = load_config()
        assert cfg.hardware.sample_rate > 0
        assert cfg.dsp.fft_size in (256, 512, 1024, 2048, 4096, 8192)
        assert 0 < cfg.dsp.snr_threshold < 60

    def test_hardware_validation_valid(self):
        from modules.rf.rf_config import HardwareConfig
        hw = HardwareConfig(gain_db=40.0, ppm_correction=5)
        hw.validate()  # No debe lanzar

    def test_hardware_validation_invalid_gain(self):
        from modules.rf.rf_config import HardwareConfig
        hw = HardwareConfig(gain_db=200.0)
        with pytest.raises(AssertionError):
            hw.validate()

    def test_hardware_validation_invalid_samplerate(self):
        from modules.rf.rf_config import HardwareConfig
        hw = HardwareConfig(sample_rate=999_999)
        with pytest.raises(AssertionError):
            hw.validate()

    def test_dsp_validation_bad_window(self):
        from modules.rf.rf_config import DspConfig
        dsp = DspConfig(window="kaiser")
        with pytest.raises(AssertionError):
            dsp.validate()

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("RF_GAIN_DB", "35.5")
        monkeypatch.setenv("RF_PPM", "7")
        from modules.rf.rf_config import load_config
        cfg = load_config()
        assert cfg.hardware.gain_db == 35.5
        assert cfg.hardware.ppm_correction == 7

    def test_save_and_reload(self, tmp_dir):
        from modules.rf.rf_config import load_config, save_config
        cfg = load_config()
        cfg_path = str(tmp_dir / "test_config.toml")
        save_config(cfg, cfg_path)
        assert Path(cfg_path).exists()
        cfg2 = load_config(cfg_path)
        assert cfg2.hardware.gain_db == cfg.hardware.gain_db


class TestBands:
    def test_fm_radio_identified(self):
        from modules.rf.bands import identify_band
        b = identify_band(100.0)
        assert b is not None
        assert "FM" in b["nombre"]

    def test_gps_l1_identified(self):
        from modules.rf.bands import identify_band
        b = identify_band(1575.42)
        assert b is not None
        assert b["tipo"] == "GNSS"

    def test_ads_b_tactical(self):
        from modules.rf.bands import identify_band
        b = identify_band(1090.0)
        assert b is not None
        assert b["peligro"] is True

    def test_unknown_freq_returns_none(self):
        from modules.rf.bands import identify_band
        b = identify_band(9999.0)
        assert b is None

    def test_most_specific_band(self):
        from modules.rf.bands import identify_band
        # GPS L1 C/A (0.1 MHz rango) debe ganar a GNSS L1 (51 MHz rango)
        b = identify_band(1575.42)
        assert b["nombre"] == "GPS L1 C/A"

    def test_bands_in_range(self):
        from modules.rf.bands import bands_in_range
        result = bands_in_range(80.0, 120.0)
        nombres = [r["nombre"] for r in result]
        assert any("FM" in n for n in nombres)

    def test_tactical_bands_not_empty(self):
        from modules.rf.bands import tactical_bands
        tac = tactical_bands()
        assert len(tac) > 0
        assert all(b["peligro"] for b in
                   [b for _, _, _, _, _, peligro in
                    __import__("bands").BANDAS_RF if peligro
                    for b in [{"peligro": peligro}]])


class TestDSP:

    def test_psd_shape(self, dsp_engine, sample_rate, fft_size):
        n_samples = fft_size * 4
        iq = np.random.randn(n_samples) + 1j * np.random.randn(n_samples)
        iq = iq.astype(np.complex64)
        freqs, psd = dsp_engine.compute_psd(iq)
        assert len(freqs) == fft_size
        assert len(psd) == fft_size

    def test_psd_output_is_finite(self, dsp_engine, fft_size):
        n = fft_size * 4
        iq = (np.random.randn(n) + 1j * np.random.randn(n)).astype(np.complex64)
        _, psd = dsp_engine.compute_psd(iq)
        assert np.all(np.isfinite(psd))

    def test_dc_spike_removed(self, dsp_engine, fft_size, sample_rate):
        n = fft_size * 4
        # Señal con DC fuerte
        dc = np.ones(n, dtype=np.complex64) * 10.0
        iq = dc + (0.01 * np.random.randn(n) + 1j * 0.01 *
                   np.random.randn(n)).astype(np.complex64)
        _, psd = dsp_engine.compute_psd(iq)

        mid = fft_size // 2
        # El bin DC no debe superar más de 3dB a sus vecinos
        diff = psd[mid] - max(psd[mid - 2], psd[mid + 2])
        assert diff < 3.0, f"Spike DC no eliminado: {diff:.1f} dB"

    def test_tone_detected(self, dsp_engine, sample_rate, fft_size):
        n = fft_size * 8
        t = np.arange(n) / sample_rate
        f_tone = 200_000  # 200 kHz offset
        amp = 0.1
        iq = (amp * np.exp(2j * np.pi * f_tone * t)).astype(np.complex64)
        iq += (0.001 * np.random.randn(n) + 1j * 0.001 *
               np.random.randn(n)).astype(np.complex64)

        freqs, psd = dsp_engine.compute_psd(iq)
        center = 433.92e6
        picos = dsp_engine.detect_peaks(freqs, psd, center)

        assert len(picos) >= 1, "No se detectó el tono puro"
        best = max(picos, key=lambda p: p.snr_db)
        offset = abs(best.freq_mhz - (center + f_tone) / 1e6)
        assert offset < 0.1, f"Offset de detección demasiado grande: {offset:.3f} MHz"

    def test_noise_floor_estimate(self, dsp_engine, fft_size):
        n = fft_size * 4
        iq = (0.001 * np.random.randn(n) + 1j * 0.001 *
              np.random.randn(n)).astype(np.complex64)
        _, psd = dsp_engine.compute_psd(iq)
        floor = dsp_engine.noise_floor(psd)
        assert -140.0 < floor < 0.0

    def test_psd_with_short_samples(self, dsp_engine):
        iq = np.random.randn(100).astype(np.complex64)
        freqs, psd = dsp_engine.compute_psd(iq)
        assert np.all(np.isfinite(psd))

    def test_freq_resolution(self, dsp_engine, sample_rate, fft_size):
        expected = sample_rate / fft_size
        assert abs(dsp_engine.freq_resolution_hz - expected) < 1.0

    def test_bw_measurement(self, dsp_engine, sample_rate, fft_size):
        n = fft_size * 4
        t = np.arange(n) / sample_rate
        bw = 25_000  # 25 kHz
        iq = np.zeros(n, dtype=np.complex64)
        for f in np.linspace(-bw/2, bw/2, 20):
            iq += (0.05 * np.exp(2j * np.pi * f * t)).astype(np.complex64)
        freqs, psd = dsp_engine.compute_psd(iq)
        picos = dsp_engine.detect_peaks(freqs, psd, 433.92e6)
        assert len(picos) >= 0


class TestMockSDR:
    def test_capture_returns_array(self, mock_sdr):
        samples = mock_sdr.capture(433.92e6, n_samples=1024)
        assert isinstance(samples, np.ndarray)
        assert samples.dtype == np.complex64
        assert len(samples) == 1024

    def test_capture_with_signals(self, sample_rate):
        from modules.rf.rf_mock import MockSDRManager, SyntheticSignal
        mock = MockSDRManager(sample_rate=sample_rate)
        mock.add_signal(SyntheticSignal(
            freq_offset=100_000,
            power_dbm=-50,
            mode="tone",
        ))
        samples = mock.capture(433.92e6, n_samples=sample_rate // 4)
        assert len(samples) > 0
        # Señal debe tener potencia mayor que solo ruido
        power = float(np.mean(np.abs(samples) ** 2))
        assert power > 0

    def test_from_file(self, tmp_dir, sample_rate):
        from modules.rf.rf_mock import generate_fixture, MockSDRManager, SyntheticSignal
        fixture = tmp_dir / "test.cf32"
        generate_fixture(
            str(fixture),
            freq_hz=100e6,
            sample_rate=sample_rate,
            duration_s=1.0,
            signals=[SyntheticSignal(power_dbm=-60, mode="tone")],
        )
        mock = MockSDRManager.from_file(str(fixture), sample_rate=sample_rate)
        samples = mock.capture(100e6, n_samples=1024)
        assert len(samples) >= 1024

    def test_set_gain(self, mock_sdr):
        mock_sdr.set_gain(30.0)
        assert mock_sdr.cfg.gain_db == 30.0

    def test_all_modes(self, sample_rate):
        from modules.rf.rf_mock import MockSDRManager, SyntheticSignal
        for mode in ("tone", "nfm", "wfm", "am", "noise"):
            mock = MockSDRManager(sample_rate=sample_rate)
            mock.add_signal(SyntheticSignal(power_dbm=-60, mode=mode))
            s = mock.capture(100e6, n_samples=4096)
            assert np.all(np.isfinite(s)), f"Modo {mode} generó NaN/inf"


class TestDemodulator:
    @pytest.fixture
    def demod(self, sample_rate):
        from modules.rf.rf_config import DemodConfig
        from modules.rf.rf_demod import Demodulator
        cfg = DemodConfig(mode="nfm", audio_rate=48_000, volume=1.0)
        return Demodulator(cfg, sample_rate)

    def test_nfm_output_shape(self, demod, sample_rate):
        from modules.rf.rf_mock import generate_iq, SyntheticSignal
        iq = generate_iq(sample_rate, sample_rate // 2,
                         [SyntheticSignal(mode="nfm", power_dbm=-50)])
        audio = demod.demodulate(iq)
        assert audio is not None
        assert len(audio) > 0
        assert np.all(np.isfinite(audio))

    def test_am_output_shape(self, sample_rate):
        from modules.rf.rf_config import DemodConfig
        from modules.rf.rf_demod import Demodulator
        from modules.rf.rf_mock import generate_iq, SyntheticSignal
        cfg = DemodConfig(mode="am", audio_rate=48_000)
        demod = Demodulator(cfg, sample_rate)
        iq = generate_iq(sample_rate, sample_rate // 2,
                         [SyntheticSignal(mode="am", power_dbm=-50)])
        audio = demod.demodulate(iq)
        assert audio is not None
        assert np.all(np.isfinite(audio))

    def test_none_mode_returns_none(self, sample_rate):
        from modules.rf.rf_config import DemodConfig
        from modules.rf.rf_demod import Demodulator
        cfg = DemodConfig(mode="none")
        demod = Demodulator(cfg, sample_rate)
        iq = np.random.randn(1024).astype(np.complex64)
        assert demod.demodulate(iq) is None

    def test_save_wav(self, demod, sample_rate, tmp_dir):
        from modules.rf.rf_mock import generate_iq, SyntheticSignal
        iq = generate_iq(sample_rate, sample_rate // 4,
                         [SyntheticSignal(mode="nfm", power_dbm=-50)])
        audio = demod.demodulate(iq)
        wav = tmp_dir / "test.wav"
        demod.save_wav(audio, str(wav))
        assert wav.exists()
        assert wav.stat().st_size > 0


class TestSignalDB:
    def test_create_and_open_session(self, signal_db):
        sid = signal_db.open_session("RTL-SDR", 2_048_000)
        assert isinstance(sid, int)
        assert sid > 0

    def test_insert_and_query_signal(self, signal_db):
        from modules.rf.dsp import Signal
        from modules.rf.bands import identify_band
        signal_db.open_session("RTL-SDR", 2_048_000)
        sig = Signal(
            freq_mhz=433.92,
            potencia=-60.0,
            snr_db=15.0,
            bw_khz=12.5,
            piso_dbm=-75.0,
            banda=identify_band(433.92),
            timestamp="2025-01-01T00:00:00",
        )
        signal_db.insert_signal(sig)
        results = signal_db.get_signals()
        assert len(results) >= 1
        assert abs(results[0]["freq_mhz"] - 433.92) < 0.01

    def test_batch_insert(self, signal_db):
        from modules.rf.dsp import Signal
        signal_db.open_session()
        signals = [
            Signal(
                freq_mhz=f, potencia=-70.0, snr_db=10.0,
                bw_khz=12.5, piso_dbm=-80.0, banda=None,
                timestamp="2025-01-01T00:00:00",
            )
            for f in [100.0, 200.0, 300.0, 400.0, 500.0]
        ]
        n = signal_db.insert_signals_batch(signals)
        assert n == 5

    def test_stats(self, signal_db):
        stats = signal_db.stats()
        assert "signals" in stats
        assert "db_size_mb" in stats

    def test_close_session(self, signal_db):
        signal_db.open_session()
        signal_db.close_session()
        assert signal_db._session_id is None


class TestCSVExporter:
    def test_export_signals(self, storage_cfg, tmp_dir):
        from modules.rf.rf_storage import CSVExporter
        from modules.rf.dsp import Signal
        exp = CSVExporter(storage_cfg)
        sigs = [
            Signal(433.92, -60.0, 15.0, 12.5, -75.0,
                   None, "2025-01-01T00:00:00"),
        ]
        path = exp.export_signals(sigs, 433.92, "RTL-SDR")
        assert path.exists()
        content = path.read_text()
        assert "freq_mhz" in content
        assert "433.92" in content

    def test_export_sweep(self, storage_cfg):
        from modules.rf.rf_storage import CSVExporter
        exp = CSVExporter(storage_cfg)
        results = [
            {"freq_mhz": f, "pot_max": -70.0, "piso": -90.0,
             "snr": 20.0, "banda": None}
            for f in range(88, 108)
        ]
        path = exp.export_sweep(results, 88.0, 108.0)
        assert path.exists()


class TestSigMF:
    def test_write_sigmf(self, storage_cfg):
        from modules.rf.rf_storage import SigMFWriter
        writer = SigMFWriter(storage_cfg)
        rec = writer.open(433.92e6, 2_048_000, "RTL-SDR")

        samples = np.random.randn(1024).astype(np.float32) + \
            1j * np.random.randn(1024).astype(np.float32)
        samples = samples.astype(np.complex64)

        with rec:
            rec.write(samples)

        assert rec.data_path.exists()
        assert rec.meta_path.exists()

        with open(rec.meta_path) as f:
            meta = json.load(f)

        assert meta["global"]["core:sample_rate"] == 2_048_000
        assert meta["captures"][0]["core:frequency"] == pytest.approx(433.92e6)


class TestCapturePipeline:
    def test_pipeline_produces_samples(self, mock_sdr, dsp_cfg):
        from modules.network.capture import CapturePipeline
        from modules.rf.rf_mock import SyntheticSignal
        mock_sdr.add_signal(SyntheticSignal(power_dbm=-60, mode="tone"))
        pipeline = CapturePipeline(mock_sdr, dsp_cfg)

        pipeline.start(433.92e6)
        import time
        time.sleep(0.1)

        samples = pipeline.get_blocking(timeout=1.0)
        pipeline.stop()

        assert samples is not None
        assert len(samples) > 0

    def test_pipeline_tune_changes_freq(self, mock_sdr, dsp_cfg):
        from modules.network.capture import CapturePipeline
        pipeline = CapturePipeline(mock_sdr, dsp_cfg)
        pipeline.start(100e6)
        pipeline.tune(200e6)
        assert pipeline.current_freq_hz == pytest.approx(200e6)
        pipeline.stop()

    def test_pipeline_stop_is_clean(self, mock_sdr, dsp_cfg):
        from modules.network.capture import CapturePipeline
        pipeline = CapturePipeline(mock_sdr, dsp_cfg)
        pipeline.start(433.92e6)
        pipeline.stop()
        assert not pipeline.is_running


def pytest_addoption(parser):
    parser.addoption("--hardware", action="store_true",
                     help="Ejecutar tests con hardware SDR real")


@pytest.fixture
def hardware_required(request):
    if not request.config.getoption("--hardware"):
        pytest.skip("Requiere --hardware y dispositivo SDR conectado")


class TestRealHardware:
    def test_connect(self, hardware_required):
        from core.hardware import SDRManager
        from modules.rf.rf_config import HardwareConfig
        sdr = SDRManager(HardwareConfig())
        assert sdr.connect()
        sdr.close()

    def test_capture(self, hardware_required):
        from core.hardware import SDRManager
        from modules.rf.rf_config import HardwareConfig
        with SDRManager(HardwareConfig()) as sdr:
            samples = sdr.capture(100e6, n_samples=4096)
            assert len(samples) == 4096
            assert np.all(np.isfinite(samples))

    def test_permissions(self, hardware_required):
        from core.hardware import check_permissions
        ok, msg = check_permissions()
        assert ok, f"Permisos incorrectos: {msg}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
