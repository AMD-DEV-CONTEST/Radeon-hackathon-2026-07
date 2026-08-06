"""
network_tool.py

Collects live network statistics.
"""

import psutil

def get_network_status():
    """
    Collect live network metrics.

    Returns:
        dict: Network Information.
    """

    net = psutil.net_io_counters()

    return {

        "bytes_sent_mb": round(net.bytes_sent / (1024 ** 2), 2),
        "bytes_received_mb": round(net.bytes_recv / (1024 ** 2),2),
        "packets_sent": net.packets_sent,
        "packets_received": net.packets_recv,
        "errors_in": net.errin,
        "errors_out": net.errout,
        "drops_in": net.dropin,
        "drops_out": net.dropout
    }
