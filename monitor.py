"""
Temperature monitoring client for the Express app.
- Fetches /history (batch)
- Consumes /stream (SSE) optionally
- Computes statistics with numpy and reports alerts for out-of-range values (default 20-80°C)
"""
from dataclasses import dataclass
from typing import List, Callable, Optional
import requests
import numpy as np
import time
import json
import threading
from datetime import datetime


@dataclass
class TemperatureReading:
    temperature: float
    timestamp: str


class TemperatureMonitor:
    """Object that stores temperature readings and computes statistics/alerts."""

    def __init__(self, safe_min: float = 20.0, safe_max: float = 80.0):
        self.safe_min = safe_min
        self.safe_max = safe_max
        self.readings: List[TemperatureReading] = []

    def add_reading(self, r: TemperatureReading) -> None:
        """Add a single reading."""
        self.readings.append(r)

    def add_readings(self, readings: List[TemperatureReading]) -> None:
        """Add multiple readings."""
        self.readings.extend(readings)

    def _temps_array(self) -> np.ndarray:
        """Return temperatures as a numpy array."""
        if not self.readings:
            return np.array([], dtype=float)
        return np.array([r.temperature for r in self.readings], dtype=float)

    def compute_stats(self) -> dict:
        """Compute count, min, max and mean using numpy."""
        arr = self._temps_array()
        if arr.size == 0:
            return {"count": 0, "min": None, "max": None, "mean": None}
        return {
            "count": int(arr.size),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "mean": float(np.mean(arr)),
        }

    def check_safety(self) -> List[TemperatureReading]:
        """Return readings outside the safe interval."""
        return [r for r in self.readings if (r.temperature < self.safe_min or r.temperature > self.safe_max)]

    def report(self) -> None:
        """Print a clear formatted report with alerts."""
        stats = self.compute_stats()
        print("=== Temperature Monitor Report ===")
        print(f"Count: {stats['count']}")
        if stats["count"] > 0:
            print(f"Min: {stats['min']:.2f} °C")
            print(f"Max: {stats['max']:.2f} °C")
            print(f"Mean: {stats['mean']:.2f} °C")
        outliers = self.check_safety()
        if not outliers:
            print("✅ All readings within safe range "
                  f"({self.safe_min:.1f}°C — {self.safe_max:.1f}°C).")
        else:
            print(f"⚠️ {len(outliers)} reading(s) OUT OF SAFE RANGE:")
            for o in outliers:
                print(f"  - {o.temperature:.2f} °C at {o.timestamp}")


class ApiClient:
    """Simple client to consume /history and /stream from the Express app."""

    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url.rstrip("/")

    def fetch_history(self) -> List[TemperatureReading]:
        """Fetch /history and return list of TemperatureReading."""
        url = f"{self.base_url}/history"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        items = resp.json()
        return [TemperatureReading(float(it["temperature"]), it["timestamp"]) for it in items]

    def stream(self, on_event: Callable[[TemperatureReading], None], stop_after: Optional[int] = None, timeout: Optional[float] = None) -> None:
        """Connect to SSE /stream and call on_event for each reading.

        stop_after: stop after N events
        timeout: stop after seconds
        """
        url = f"{self.base_url}/stream"
        with requests.get(url, stream=True, timeout=(3.05, None)) as resp:
            resp.raise_for_status()
            event_count = 0
            start = time.time()
            buffer = ""
            for chunk in resp.iter_content(chunk_size=1):
                if not chunk:
                    continue
                try:
                    ch = chunk.decode("utf-8")
                except Exception:
                    continue
                buffer += ch
                if buffer.endswith("\n\n"):
                    # SSE event ended
                    lines = [ln for ln in buffer.splitlines() if ln.strip() != ""]
                    for ln in lines:
                        if ln.startswith("data:"):
                            payload = ln[len("data:"):].strip()
                            try:
                                obj = json.loads(payload)
                                r = TemperatureReading(float(obj["temperature"]), obj["timestamp"])
                                on_event(r)
                                event_count += 1
                            except Exception:
                                pass
                    buffer = ""
                if stop_after and event_count >= stop_after:
                    break
                if timeout and (time.time() - start) >= timeout:
                    break

    def stream_forever(self, on_event: Callable[[TemperatureReading], None], stop_event: threading.Event) -> None:
        """Continuously consume /stream until stop_event is set. Reconnects on transient errors.

        This method is suitable to run in a background thread. It will try to reconnect
        if the connection drops, and will exit promptly when stop_event is set.
        """
        url = f"{self.base_url}/stream"
        while not stop_event.is_set():
            try:
                with requests.get(url, stream=True, timeout=(3.05, 10)) as resp:
                    resp.raise_for_status()
                    buffer = ""
                    for chunk in resp.iter_content(chunk_size=1):
                        if stop_event.is_set():
                            break
                        if not chunk:
                            continue
                        try:
                            ch = chunk.decode("utf-8")
                        except Exception:
                            continue
                        buffer += ch
                        if buffer.endswith("\n\n"):
                            lines = [ln for ln in buffer.splitlines() if ln.strip() != ""]
                            for ln in lines:
                                if ln.startswith("data:"):
                                    payload = ln[len("data:"):].strip()
                                    try:
                                        obj = json.loads(payload)
                                        r = TemperatureReading(float(obj["temperature"]), obj["timestamp"])
                                        on_event(r)
                                    except Exception:
                                        pass
                            buffer = ""
            except requests.exceptions.RequestException:
                if stop_event.is_set():
                    break
                # transient error, wait a bit then retry
                time.sleep(1)
                continue


# Demo usage
if __name__ == "__main__":
    client = ApiClient("http://localhost:3000")
    monitor = TemperatureMonitor(safe_min=20.0, safe_max=80.0)

    def handle_event(reading: TemperatureReading):
        # improved real-time logging with timestamp and emojis for alerts
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        t = reading.temperature
        ts = reading.timestamp
        emoji = "✅"
        alert = ""
        if t < monitor.safe_min:
            emoji = "❄️"
            alert = f" ⛔ BELOW safe_min ({monitor.safe_min}°C)"
        elif t > monitor.safe_max:
            emoji = "🔥"
            alert = f" ⛔ ABOVE safe_max ({monitor.safe_max}°C)"
        elif t == monitor.safe_min or t == monitor.safe_max:
            emoji = "⚠️"
            alert = f" ⚠️ REACHED boundary ({monitor.safe_min if t==monitor.safe_min else monitor.safe_max}°C)"
        print(f"[{now}] {emoji} {t:.2f} °C at {ts}{alert}")
        monitor.add_reading(reading)

    def fetch_and_show_history() -> List[TemperatureReading]:
        try:
            history = client.fetch_history()
            print(f"Loaded {len(history)} readings from /history (showing up to 20)")
            for i, r in enumerate(history[:20], 1):
                print(f"{i:3d}. {r.temperature:.2f} °C at {r.timestamp}")
            if len(history) > 20:
                print(f"... ({len(history)-20} more entries)")
            return history
        except Exception as e:
            print(f"Could not fetch history: {e}")
            return []

    def analyze_history_only() -> None:
        # fetch history but print ONLY min, max and mean (three lines)
        try:
            history = client.fetch_history()
            temps = np.array([float(it.temperature) for it in history], dtype=float) if history else np.array([], dtype=float)
            if temps.size == 0:
                print("Min: -")
                print("Max: -")
                print("Mean: -")
                return
            print(f"Min: {np.min(temps):.2f}")
            print(f"Max: {np.max(temps):.2f}")
            print(f"Mean: {np.mean(temps):.2f}")
        except Exception:
            # per requirement, do not print extra messages; show placeholders
            print("Min: -")
            print("Max: -")
            print("Mean: -")

    def show_cold_violations() -> None:
        low = [r for r in monitor.readings if r.temperature <= monitor.safe_min]
        print(f"\n--- Cold readings <= {monitor.safe_min}°C ({len(low)}) ---")
        if low:
            for i, r in enumerate(low, 1):
                print(f"❄️ {i:3d}. {r.temperature:.2f} °C at {r.timestamp}")
        else:
            print("None ✅")

    def show_hot_violations() -> None:
        high = [r for r in monitor.readings if r.temperature >= monitor.safe_max]
        print(f"\n--- Hot readings >= {monitor.safe_max}°C ({len(high)}) ---")
        if high:
            for i, r in enumerate(high, 1):
                print(f"🔥 {i:3d}. {r.temperature:.2f} °C at {r.timestamp}")
        else:
            print("None ✅")

    while True:
        print("\n=== Temperature Monitor Menu ===")
        print("1) View history (sample)")
        print("2) Stream live readings (infinite, press ENTER to stop)")
        print("3) Analyze history (mean/min/max)")
        print("4) Show cold violations (<= safe_min)")
        print("5) Show hot violations (>= safe_max)")
        print("0) Exit")
        choice = input("Select option: ").strip()

        if choice == "1":
            fetch_and_show_history()

        elif choice == "2":
            print("Starting infinite stream. Press ENTER to stop and return to menu.")
            stop_event = threading.Event()
            t = threading.Thread(target=client.stream_forever, args=(handle_event, stop_event), daemon=True)
            t.start()
            try:
                input()  # wait for user to press ENTER
            except KeyboardInterrupt:
                pass
            stop_event.set()
            t.join(timeout=5)
            print(f"Streaming stopped. Accumulated readings: {len(monitor.readings)}")

        elif choice == "3":
            analyze_history_only()

        elif choice == "4":
            show_cold_violations()

        elif choice == "5":
            show_hot_violations()

        elif choice == "0":
            print("Exiting.")
            break

        else:
            print("Invalid option. Please choose a valid number.")
