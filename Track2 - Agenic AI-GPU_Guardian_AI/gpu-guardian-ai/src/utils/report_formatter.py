"""
report_formatter.py

Formats GPU and CPU metrics into a structured report for the LLM.
"""


def format_system_report(
        gpu, 
        gpu_health, 
        cpu, 
        cpu_health, 
        memory, 
        memory_health, 
        disk,
        disk_health,
        network,
        network_health,
        system_health,
        diagnosis,
        recommendations,
        insights
):
    """
    Create a formatted System Health report.

    Args:
        gpu (dict): Live GPU metrics
        gpu_health (dict): GPU health evaluation
        cpu (dict): Live CPU metrics
        cpu_health (dict): CPU health evaluation

    Returns:
        str: Formatted report
    """

    report = f"""
==================================================
SYSTEM HEALTH REPORT
==================================================

==================== GPU ==========================

Device               : {gpu.get('device', 'Unknown')}
GPU Available        : {gpu.get('available', False)}

--------------------------------------------------
GPU Metrics
--------------------------------------------------

Edge Temperature     : {gpu.get('edge_temp', 'N/A')} °C
Junction Temperature : {gpu.get('junction_temp', 'N/A')} °C
Memory Temperature   : {gpu.get('memory_temp', 'N/A')} °C

GPU Usage            : {gpu.get('gpu_usage', 'N/A')} %
VRAM Usage           : {gpu.get('vram_usage', 'N/A')} %

Power Consumption    : {gpu.get('power', 'N/A')} W

--------------------------------------------------
GPU Health
--------------------------------------------------

Overall Status       : {gpu_health.get('overall', 'Unknown')}

Temperature          : {gpu_health.get('temperature', 'Unknown')}
GPU Usage            : {gpu_health.get('gpu_usage', 'Unknown')}
VRAM Usage           : {gpu_health.get('vram_usage', 'Unknown')}
Power                : {gpu_health.get('power', 'Unknown')}

Recommendation

{gpu_health.get('recommendation', 'No recommendation available.')}

==================================================
CPU INFORMATION
==================================================

CPU Usage            : {cpu.get('cpu_usage', 'N/A')} %

Physical Cores       : {cpu.get('cpu_cores_physical', 'N/A')}

Logical Cores        : {cpu.get('cpu_cores_logical', 'N/A')}

CPU Frequency        : {cpu.get('cpu_frequency', 'N/A')} MHz

Load Average         : {cpu.get('load_average', 'N/A')}

--------------------------------------------------
CPU Health
--------------------------------------------------

Overall Status       : {cpu_health.get('overall', 'Unknown')}

CPU Usage            : {cpu_health.get('cpu_usage', 'Unknown')}

Recommendation

{cpu_health.get('recommendation', 'No recommendation available.')}


==================================================
MEMORY INFORMATION
==================================================

Total Memory        : {memory.get('total_gb', 'N/A')} GB

Used Memory         : {memory.get('used_gb', 'N/A')} GB

Available Memory    : {memory.get('available_gb', 'N/A')} GB

Memory Usage        : {memory.get('memory_usage', 'N/A')} %

--------------------------------------------------
Memory Health
--------------------------------------------------

Overall Status      : {memory_health.get('overall', 'Unknown')}

Memory Usage        : {memory_health.get('memory_usage', 'Unknown')}

Recommendation

{memory_health.get('recommendation', 'No recommendation available.')}

==================================================
DISK INFORMATION
==================================================

Total Disk          : {disk.get('total_gb', 'N/A')} GB

Used Disk           : {disk.get('used_gb', 'N/A')} GB

Free Disk           : {disk.get('free_gb', 'N/A')} GB

Disk Usage          : {disk.get('disk_usage', 'N/A')} %

--------------------------------------------------
Disk Health
--------------------------------------------------

Overall Status      : {disk_health.get('overall', 'Unknown')}

Disk Usage          : {disk_health.get('disk_usage', 'Unknown')}

Recommendation

{disk_health.get('recommendation', 'No recommendation available.')}

==================================================
NETWORK INFORMATION
==================================================

Bytes Sent          : {network.get('bytes_sent_mb', 'N/A')} MB

Bytes Received      : {network.get('bytes_received_mb', 'N/A')} MB

Packets Sent        : {network.get('packets_sent', 'N/A')}

Packets Received    : {network.get('packets_received', 'N/A')}

Errors In           : {network.get('errors_in', 'N/A')}

Errors Out          : {network.get('errors_out', 'N/A')}

Drops In            : {network.get('drops_in', 'N/A')}

Drops Out           : {network.get('drops_out', 'N/A')}

--------------------------------------------------
Network Health
--------------------------------------------------

Overall Status      : {network_health.get('overall', 'Unknown')}

Network             : {network_health.get('network', 'Unknown')}

Recommendation

{network_health.get('recommendation', 'No recommendation available.')}


==================================================
OVERALL SYSTEM HEALTH
==================================================

Overall Status       : {system_health.get('overall', 'Unknown')}

Severity             : {system_health.get('severity', 'Unknown')}

Summary

{system_health.get('summary', 'No summary available.')}

Recommendation

{system_health.get('recommendation', 'No recommendation available.')}

==================================================

==================================================
KEY INSIGHTS
==================================================

"""
    for insight in insights:
        report += f"- {insight}\n"

    report += """


==================================================
INTELLIGENT DIAGNOSIS
==================================================

"""

    for item in diagnosis:

        report += f"""
--------------------------------------------------
Severity        : {item.get('severity', 'Unknown')}

Category        : {item.get('category', 'Unknown')}

Finding         : {item.get('finding', 'Unknown')}

Root Cause

{item.get('root_cause', 'Not Available')}

Impact

{item.get('impact', 'Not Available')}

Recommendation

{item.get('recommendation', 'No recommendation available.')}
"""
    report += """

==================================================
PRIORITIZED RECOMMENDATIONS
==================================================

"""

    for item in recommendations:

        report += f"""
[{item['severity']}] {item['category']}

{item['recommendation']}

"""

    report += """

==================================================
"""
    return report
#    report += """

#==================================================
#"""

#    return report
