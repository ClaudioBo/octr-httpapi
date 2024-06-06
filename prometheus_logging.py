import os

try:
    from prometheus_client import Gauge, Enum, start_http_server
    prometheus_available = True
except ImportError:
    prometheus_available = False

gauge_list = {}

def add_server(address):
    if not prometheus_available: return
    ipaddr, _ = address.split(":")

    gauge_name = f'{ipaddr}_total_players'.replace('-', '_').replace('.', '_')
    gauge_list[ipaddr] = Gauge(gauge_name, 'Total players connected on this server')

def set_player_count_server(address, count):
    if not prometheus_available: return
    ipaddr, _ = address.split(":")
    gauge_list[ipaddr].set(count)

async def start_prometheus_server():
    if prometheus_available:
        start_http_server(int(os.getenv("PROMETHEUS_PORT")))
        print(f"Prometheus server started on port {os.getenv('PROMETHEUS_PORT')}")
    else:
        print("Prometheus library not found. Ignoring.")
