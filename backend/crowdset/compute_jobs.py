"""Resource declarations for the existing fenced Crowdset media protocol."""
from compute.jobs import Resources

RESOURCES = {
    'process': Resources(cpu=4, memory_mb=8192, gpu=1),
    'ingest': Resources(cpu=2, memory_mb=2048),
    'youtube': Resources(cpu=2, memory_mb=2048),
}


def resources(kind, encoder='h264_nvenc'):
    if encoder not in ('h264_nvenc', 'libx264') or kind not in RESOURCES:
        raise ValueError('Unknown Crowdset workload or encoder')
    value = RESOURCES[kind]
    return value.model_copy(update={'gpu': 0}) if kind == 'process' and encoder == 'libx264' else value
