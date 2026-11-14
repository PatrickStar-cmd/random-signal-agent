"""Resumable, single-frame execution of the existing digital receiver engine."""
import copy
import hashlib
import numpy as np
from src import communication_runtime as runtime

# These are the numerical engine's live values at a block boundary. Program
# features are rebuilt for each receiver; random and filter state are frozen.
VARIABLES = (
    'data', 'reference', 'stack', 'info', 'snapshots', 'recovery', 'gain', 'prefix',
    'fs', 'tx', 'channel', 'tx_power', 'in_channel', 'decoded_bits', 'clipped',
    'corrections', 'eye', 'noise_estimate', 'rf_stages', 'learning',
    'algorithm_traces', 'wireless_state', 'encoded', 'scheme', 'modulation',
    'transmitted_indices', 'mapped', 'preamble', 'demapped', 'decided_indices',
    'decision_symbols', 'points', 'variance', 'decision_variance',
)


class Suspended(Exception):
    pass


def checkpoint(index, scope):
    ctx = runtime.CURRENT.get()
    if ctx is None or index not in getattr(ctx, 'capture_indices', ()):
        return
    ctx.snapshot = copy.deepcopy({
        'index': index,
        'source': scope['source'], 'texts': scope['texts'],
        'source_count': scope['source_count'],
        'variables': {key: scope[key] for key in VARIABLES},
        'rng_state': scope['rng'].bit_generator.state,
        'states': ctx.states,
        'observations': ctx.observations, 'values': ctx.values,
    })
    if index == ctx.stop_after:
        raise Suspended()


def execute(compiled, resume=None, stop_after=None, cancel=None, gate=None,
            on_context=None, scope=None, initial=None):
    from src import communications as c
    if compiled.get('transport') != 'advanced' or compiled['source_kind'] == 'analog':
        raise ValueError('分段执行请选择数字复基带接收链路。')
    ctx = runtime.Observer(compiled, retain=True, states={}, cancel=cancel, gate=gate)
    ctx.scope = scope
    ctx.resume = copy.deepcopy(resume)
    ctx.stop_after = stop_after
    ctx.capture_indices = {stop_after} if stop_after is not None else set()
    ctx.snapshot = None
    if resume:
        ctx.states = copy.deepcopy(resume['states'])
        ctx.observations = copy.deepcopy(resume['observations'])
        for row in ctx.observations:
            row['reused'] = True
            row['elapsed_ms'] = 0.
        ctx.values = copy.deepcopy(resume['values'])
    if on_context: on_context(ctx)
    if initial:
        block, values, domain = initial
        ctx.plan[block['id']] = {'output': domain}
        ctx.record(block, values, compiled['program']['symbol_rate'])
        ctx.observations[-1].update(label=block['label'], elapsed_ms=0.)
    start = len(ctx.observations)
    result = None
    with runtime.execution(ctx):
        try:
            result = c.run(compiled['program'], compiled['token'])
        except Suspended:
            pass
    ctx.resume = None
    executed = [row['id'] for row in ctx.observations[start:]]
    if result is not None:
        result['experience'] = {'observations': ctx.observations, 'frame': 0,
                                'contract': 1, 'executed': executed}
    return result, ctx, executed


def input_hash(snapshot):
    array = np.ascontiguousarray(snapshot['variables']['data'])
    return hashlib.sha256(array.dtype.str.encode() + str(array.shape).encode() + array.tobytes()).hexdigest()
