"""Versioned, typed subproject definitions expanded into isolated block instances."""
import copy
import hashlib
import re
import uuid


def validate(definition):
    from src import communications as c, communication_studio as studio
    if not isinstance(definition, dict): raise ValueError('子工程定义需要 JSON 对象。')
    d = copy.deepcopy(definition)
    if not isinstance(d.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', d['id']): raise ValueError('子工程标识需要 1–64 位字母、数字或下划线。')
    if not isinstance(d.get('name'), str) or not 1 <= len(d['name'].strip()) <= 80: raise ValueError('子工程名称需要 1–80 个字符。')
    d['name'] = d['name'].strip(); d['version'] = c.numeric(d.get('version', 1), '子工程版本', 1, 100000, True)
    p = c.normalize({'schema': 1, **c.CONFIG['defaults'], 'blocks': d.get('blocks')}, draft=True); d['blocks'] = p['blocks']
    ports = d.get('ports')
    if not isinstance(ports, dict) or set(ports) != {'input', 'output'}: raise ValueError('子工程需要命名的 input / output 端口。')
    for port in ports.values():
        if not isinstance(port, dict) or not isinstance(port.get('name'), str) or not 1 <= len(port['name']) <= 40 or not isinstance(port.get('domain'), str): raise ValueError('端口需要名称和信号类型。')
    domain = ports['input']['domain']
    for block in d['blocks']:
        accepts, output = studio.contract(block['kind'])
        if block['kind'] == 'iq_source': output = ('复符号', '复波形', 'OFDM 波形')[block['params']['mode']]
        if domain not in accepts and block['kind'] not in c.SOURCES: raise ValueError(f'子工程内 {c.BLOCKS[block["kind"]]["label"]} 的输入类型需要 {" / ".join(accepts)}。')
        if output not in ('同输入', '信宿'): domain = output
    if domain != ports['output']['domain']: raise ValueError('输出端口类型与子工程处理结果一致后即可保存。')
    parameters = d.get('parameters', [])
    if not isinstance(parameters, list) or len(parameters) > 64: raise ValueError('子工程公开参数最多 64 项。')
    blocks = {b['id']: b for b in d['blocks']}; names = set(); targets = set()
    for item in parameters:
        name = item.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', name) or name in names: raise ValueError('公开参数名称使用唯一的英文字母开头标识。')
        names.add(name)
        if not isinstance(item.get('targets'), list) or not item['targets']: raise ValueError('公开参数需要至少一个 block-id:param 目标。')
        for target in item['targets']:
            parts = target.rsplit(':', 1) if isinstance(target, str) else []
            if len(parts) != 2 or parts[0] not in blocks or parts[1] not in c.BLOCKS[blocks[parts[0]]['kind']]['params'] or target in targets: raise ValueError('公开参数目标需要属于子工程且每个目标仅绑定一次。')
            targets.add(target)
        first, key = item['targets'][0].rsplit(':', 1)
        item.setdefault('default', blocks[first]['params'].get(key, c.BLOCKS[blocks[first]['kind']]['params'][key]['default']))
        item.setdefault('label', name)
    d['parameters'] = parameters
    return d


def create(program, block_ids, name, parameters=None):
    from src import communications as c, communication_studio as studio
    p = c.normalize(program, draft=True)
    if not isinstance(block_ids, list) or not block_ids or len(set(block_ids)) != len(block_ids): raise ValueError('请选择连续的一组积木。')
    positions = [i for i, b in enumerate(p['blocks']) if b['id'] in block_ids]
    if len(positions) != len(block_ids) or positions != list(range(positions[0], positions[-1]+1)): raise ValueError('子工程由连续积木组成。')
    selected = p['blocks'][positions[0]:positions[-1]+1]
    ports = studio.describe(p)['ports']; start, end = ports[positions[0]], ports[positions[-1]]
    definition = {'id': 'module-'+uuid.uuid4().hex[:16], 'name': name, 'version': 1, 'blocks': selected,
                  'ports': {'input': {'name': 'in', 'domain': start['input']}, 'output': {'name': 'out', 'domain': end['output']}},
                  'parameters': parameters or []}
    return validate(definition)


def expansion(definition, instance_id, parameters=None):
    from src import communications as c
    d = validate(definition)
    if not isinstance(instance_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', instance_id): raise ValueError('实例标识需要 1–64 位字母、数字或下划线。')
    parameters = parameters or {}
    if not isinstance(parameters, dict) or set(parameters)-{p['name'] for p in d['parameters']}: raise ValueError('实例参数需要使用定义中的公开名称。')
    blocks = copy.deepcopy(d['blocks']); lookup = {b['id']: b for b in blocks}; values = {}
    for spec in d['parameters']:
        value = parameters.get(spec['name'], spec['default']); values[spec['name']] = value
        for target in spec['targets']:
            bid, key = target.rsplit(':', 1); lookup[bid]['params'][key] = value
    # The numerical engine keys all persistent algorithm state by block ID.
    prefix = 'sp-'+hashlib.sha256(instance_id.encode()).hexdigest()[:12]+'-'
    mapping = {b['id']: prefix+hashlib.sha256(b['id'].encode()).hexdigest()[:12] for b in blocks}
    for block in blocks: block['id'] = mapping[block['id']]
    instance = {'id': instance_id, 'definition_id': d['id'], 'version': d['version'], 'name': d['name'],
                'parameters': values, 'members': [b['id'] for b in blocks], 'block_map': mapping, 'ports': copy.deepcopy(d['ports'])}
    return blocks, instance


def insert(program, definition, instance_id=None, parameters=None, index=None):
    from src import communications as c
    p = c.normalize(program, draft=True)
    index = c.numeric(len(p['blocks'])-1 if index is None else index, '插入位置', 0, len(p['blocks']), True)
    blocks, instance = expansion(definition, instance_id or 'instance-'+uuid.uuid4().hex[:16], parameters)
    p['blocks'][index:index] = blocks
    return {'program': c.normalize(p, draft=True), 'instance': instance}


def update(program, definition, instance, parameters=None):
    from src import communications as c
    d = validate(definition); p = c.normalize(program, draft=True)
    if instance.get('definition_id') != d['id']: raise ValueError('更新需要选择同一个子工程定义。')
    members = instance.get('members', []); indices = [i for i, b in enumerate(p['blocks']) if b['id'] in members]
    if not indices or len(indices) != len(members) or indices != list(range(indices[0], indices[-1]+1)): raise ValueError('实例积木保持相邻后即可更新公开参数。')
    blocks, replaced = expansion(d, instance['id'], instance.get('parameters', {}) if parameters is None else parameters)
    p['blocks'][indices[0]:indices[-1]+1] = blocks
    return {'program': c.normalize(p, draft=True), 'instance': replaced}


def validate_document(document):
    value = document.get('subprojects')
    if value is None: return
    if not isinstance(value, dict) or not isinstance(value.get('definitions', []), list) or not isinstance(value.get('instances', []), list): raise ValueError('子工程库需要 definitions 与 instances 列表。')
    definitions = [validate(d) for d in value.get('definitions', [])]
    if len(definitions) > 64 or len(value.get('instances', [])) > 32: raise ValueError('工程最多保存 64 个子工程定义版本和 32 个实例。')
    keys = [(d['id'], d['version']) for d in definitions]
    if len(keys) != len(set(keys)): raise ValueError('每个子工程定义版本需要唯一。')
    ids = {b['id'] for b in document['program']['blocks']}; used = set()
    for instance in value.get('instances', []):
        if (instance.get('definition_id'), instance.get('version')) not in keys: raise ValueError('实例需要保留对应版本的子工程定义。')
        if instance.get('id') in used: raise ValueError('子工程实例标识需要唯一。')
        used.add(instance.get('id'))
        if not instance.get('members') or any(bid not in ids for bid in instance['members']): raise ValueError('实例成员需要存在于当前工程中。')
    value['definitions'] = definitions
