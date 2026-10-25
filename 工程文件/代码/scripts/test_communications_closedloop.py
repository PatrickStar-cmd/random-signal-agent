"""v0.4.8 reusable instances and closed-loop execution on the actual PHY."""
import copy
import json
import sys
import threading
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_studio as studio
from src import communication_protocols as link, communication_subprojects as modules
from src import communication_runtime as runtime


def program(snr=20):
    return c.preset(['random_bits','mod_qpsk','awgn','demod_qpsk','sink'], {0:{'count':512},2:{'esn0_db':snr}})


class SubprojectTests(unittest.TestCase):
    def test_ports_public_parameters_and_cross_project_instances(self):
        original = c.preset(['random_bits','mod_qpsk','attenuation','awgn','demod_qpsk','sink'])
        definition = modules.create(original,['block-2'],'可复用信道',[{'name':'loss','targets':['block-2:db'],'default':2}])
        self.assertEqual(definition['ports']['input']['domain'],'复符号')
        self.assertEqual(definition['ports']['output']['domain'],'复符号')
        saved = json.loads(json.dumps(definition))
        first = modules.insert(program(),saved,'first',{'loss':1},2)
        second = modules.insert(first['program'],saved,'second',{'loss':3},3)
        self.assertNotEqual(first['instance']['members'],second['instance']['members'])
        changed = modules.update(second['program'],saved,first['instance'],{'loss':4})
        members = {b['id']:b for b in changed['program']['blocks']}
        self.assertEqual(members[first['instance']['members'][0]]['params']['db'],4)
        self.assertEqual(members[second['instance']['members'][0]]['params']['db'],3)
        compiled = c.build(changed['program']); self.assertEqual(c.run(compiled['program'],compiled['token'])['sink']['count'],512)
        document = studio.validate_document({'document_schema':2,'name':'复用工程','program':changed['program'],
                    'subprojects':{'definitions':[saved],'instances':[changed['instance'],second['instance']]}})
        self.assertEqual(document['subprojects']['instances'][1]['id'],'second')

    def test_instance_runtime_state_and_version_are_independent(self):
        p = c.preset(['random_bits','mod_qpsk','attenuation','awgn','demod_qpsk','sink'])
        d = modules.create(p,['block-2'],'衰减')
        a = modules.insert(program(),d,'a',index=2); b = modules.insert(a['program'],d,'b',index=3)
        states = {}; observer = runtime.Observer(c.build(b['program']),states=states)
        with runtime.execution(observer):
            for instance,value in ((a['instance'],7),(b['instance'],9)):
                runtime.enter(next(block for block in b['program']['blocks'] if block['id']==instance['members'][0]))
                runtime.state('counter',lambda:{'value':0})['value']=value
        self.assertEqual(sorted(value['value'] for value in states.values()),[7,9])
        newer = copy.deepcopy(d); newer['version']=2
        updated = modules.update(b['program'],newer,a['instance'])
        self.assertEqual(updated['instance']['version'],2); self.assertEqual(b['instance']['version'],1)

    def test_port_and_binding_validation(self):
        p = program()
        with self.assertRaises(ValueError): modules.create(p,['block-0','block-2'],'非连续')
        d = modules.create(p,['block-2'],'噪声')
        d['ports']['output']['domain']='比特'
        with self.assertRaises(ValueError): modules.validate(d)
        d['ports']['output']['domain']='复符号'; d['parameters']=[{'name':'snr','targets':['missing:esn0_db']}]
        with self.assertRaises(ValueError): modules.validate(d)


class ClosedLoopTests(unittest.TestCase):
    def test_packets_use_actual_channel_and_actual_duration(self):
        good = link.protocol(program(30),{'phy':'program','packets':2,'feedback_loss':0,'max_retries':0})
        bad = link.protocol(program(-10),{'phy':'program','packets':2,'feedback_loss':0,'max_retries':0})
        self.assertTrue(good['metrics']['complete_payload']); self.assertGreater(bad['metrics']['ber'],0)
        self.assertEqual(good['metrics']['bit_count'],256)
        self.assertEqual(good['events'][0]['executed_kinds'],['bit_pattern','mod_qpsk','awgn','demod_qpsk','sink'])
        self.assertAlmostEqual(good['events'][0]['duration_seconds'],88/1000)
        self.assertEqual(good['source_base64'],good['received_base64'])
        self.assertEqual(good['actual_program']['blocks'][2]['params']['esn0_db'],30)

    def test_chase_combines_actual_llrs_and_keeps_first_decode(self):
        p = program(0); packet = link.packetize(link.source_bits(p),16)[0]
        decoded1, first, _ = link.run_packet(p,packet,101,None,{})
        decoded2, second, _ = link.run_packet(p,packet,102,None,{},first.combined)
        np.testing.assert_array_equal(second.combined,first.llr+second.llr)
        np.testing.assert_array_equal(decoded2,(second.combined<0).astype(np.uint8))
        injected = link.packet_program(p,packet['wire'],101)
        baseline = c.run(injected['program'],injected['token'])
        np.testing.assert_array_equal(decoded1,baseline['sink']['values'])
        soft = c.preset(['random_bits','conv_encode','mod_qpsk','awgn','soft_qpsk','conv_soft_decode','sink'])
        result = link.protocol(soft,{'phy':'program','mode':'harq','packets':2,'feedback_loss':0})
        self.assertTrue(result['metrics']['complete_payload'])
        self.assertIn('conv_soft_decode',result['events'][0]['executed_kinds'])

    def test_physical_waveform_wireless_and_spatial_chains(self):
        for key in ('ofdm','dsss_interference','dsss_rake','mimo_mmse','mimo_mmse_sic','mimo_ofdm_mmse','ofdma_fair','fhss_antijamming'):
            with self.subTest(preset=key):
                p = copy.deepcopy(c.PRESETS[key]['program'])
                result = link.protocol(p,{'phy':'program','packets':1,'feedback_loss':0,'max_retries':1})
                original = [b['kind'] for b in p['blocks'] if b['kind'] not in c.SOURCES]
                executed = result['events'][0]['executed_kinds']
                self.assertEqual([kind for kind in executed if kind!='bit_pattern'],original)
                self.assertTrue(result['metrics']['complete_payload'])
                self.assertGreater(result['events'][0]['tx_energy'],0)

    def test_actual_amc_adapts_mapping_coding_and_feedback(self):
        for coding in ('preserve','convolutional'):
            with self.subTest(coding=coding):
                result = link.amc(program(),{'phy':'program','coding':coding,'frames':12,'snr_start':0,'snr_stop':28,'feedback_delay':1})
                rows = result['frames']; self.assertIsNone(rows[0]['feedback_snr_db']); self.assertIsNone(rows[1]['feedback_snr_db'])
                self.assertEqual(rows[2]['feedback_snr_db'],rows[0]['estimated_snr_db'])
                self.assertGreater(result['metrics']['profile_switches'],0)
                self.assertEqual(result['actual_program']['blocks'][next(i for i,b in enumerate(result['actual_program']['blocks']) if b['id']=='block-2')]['params']['esn0_db'],28)
                self.assertEqual('conv_encode' in rows[-1]['executed_kinds'],coding=='convolutional')
                self.assertEqual(rows[-1]['code_rate']==1,coding=='preserve')

    def test_feedback_loss_duplicate_and_cancellation(self):
        result = link.protocol(program(30),{'phy':'program','packets':1,'feedback_loss':1,'max_retries':2})
        self.assertEqual(result['metrics']['transmissions'],3); self.assertEqual(result['metrics']['delivered_packets'],1)
        self.assertTrue(result['events'][1]['duplicate'])
        event = threading.Event(); event.set()
        with self.assertRaises(runtime.Cancelled): link.protocol(program(),{'phy':'program'},cancel=event)
        with self.assertRaises(runtime.Cancelled): link.amc(program(),{'phy':'program'},cancel=event)

    def test_ofdma_amc_preserves_user_snr_offsets_and_word_boundaries(self):
        result = link.amc(c.PRESETS['ofdma_fair']['program'],{'phy':'program','frames':10,'snr_start':20,'snr_stop':45,'feedback_delay':0})
        last = result['frames'][-1]; self.assertEqual(last['scheme'],'qam64'); self.assertEqual(last['wire_padding_bits'],4)
        actual = result['actual_program']; sources = [b for b in actual['blocks'] if b['kind']=='bit_pattern']
        self.assertEqual(len(sources),3); self.assertTrue(all(len(b['params']['pattern'])%6==0 for b in sources))
        self.assertEqual(next(b for b in actual['blocks'] if b['kind']=='ofdma_channel')['params']['snrs'],'45.0,41.0,39.0')
        self.assertEqual(result['metrics']['fer'],0)
        self.assertAlmostEqual(last['estimated_snr_db'],-10*np.log10(last['estimated_noise_variance']))

    def test_packet_latency_counts_waveform_overhead_and_channel_tail(self):
        p = c.PRESETS['fhss_antijamming']['program']
        result = link.protocol(p,{'phy':'program','packets':1,'feedback_loss':0})
        event = result['events'][0]
        self.assertAlmostEqual(event['channel_tail_seconds'],38/(1000*16))
        self.assertAlmostEqual(event['duration_seconds'],event['tx_duration_seconds']+event['channel_tail_seconds'])
        self.assertAlmostEqual(event['receive_seconds'],event['duration_seconds'])
        p = c.PRESETS['mimo_ofdm_mmse']['program']; packet = link.packetize(link.source_bits(p),16)[0]
        _,_,detail = link.run_packet(p,packet,17,None,{})
        candidate = c.build(detail['program']); actual = c.run(candidate['program'],candidate['token'])
        arrays = actual['advanced']['wireless']['tx_mimo_ofdm']['full_tx']
        energy = np.sum(np.asarray(arrays['i'])**2+np.asarray(arrays['q'])**2)
        self.assertAlmostEqual(detail['tx_energy'],energy)
        self.assertAlmostEqual(detail['tx_duration_seconds'],len(arrays['i'])/(1000*32))

    def test_new_wireless_ports_and_receiver_completion(self):
        for key in ('mimo_mmse_sic','mimo_mobile_tracking','mimo_ofdm_mmse','ofdma_fair','fhss_antijamming'):
            with self.subTest(preset=key):
                p = copy.deepcopy(c.PRESETS[key]['program'])
                self.assertTrue(all(row['compatible'] for row in studio.describe(p)['ports']))
                p['blocks']=[b for b in p['blocks'] if not b['kind'].startswith('rx_')]
                completed = studio.complete_receiver(p)
                self.assertTrue(studio.describe(completed)['ready'])

    def test_iq_receiver_completion_uses_recorded_format(self):
        from src import communication_iq as iq
        cases=[(['random_bits','mod_qpsk','ideal','demod_qpsk','sink'],[1]),
               (['random_bits','mod_qpsk','tx_rrc','ideal','rx_matched','rx_timing','demod_qpsk','sink'],[3,4]),
               (['random_bits','mod_qpsk','tx_frame','tx_rrc','ideal','rx_matched','rx_timing','rx_frame','demod_qpsk','sink'],[4]),
               (['random_bits','mod_qpsk','tx_ofdm','ideal','rx_ofdm','demod_qpsk','sink'],[3])]
        for kinds,points in cases:
            original=c.build(c.preset(kinds)); _,capture=runtime.observe_run(original['program'],original['token'],retain=True)
            for point in points:
                with self.subTest(mode=kinds,point=point):
                    bid=original['program']['blocks'][point]['id']; sample=next(o for o in capture.observations if o['id']==bid)
                    exported=iq.export_recording(capture.values[bid],sample['sample_rate'],original['program'],bid,sample['domain'])
                    imported=iq.import_recording(exported['data'],name='completion.sigmf')['program']
                    imported['blocks']=[imported['blocks'][0],imported['blocks'][-1]]
                    completed=studio.complete_receiver(imported); built=c.build(completed)
                    _,received=runtime.observe_run(built['program'],built['token'],retain=True)
                    np.testing.assert_array_equal(received.values[built['program']['blocks'][-1]['id']],capture.values[original['program']['blocks'][-1]['id']])
                    q=completed['blocks'][0]['params']
                    self.assertEqual(sum(b['kind']=='rx_matched' for b in completed['blocks']),int(q['mode']==1 and not q['matched']))
                    self.assertEqual(sum(b['kind']=='rx_frame' for b in completed['blocks']),int(q['framed']))

    def test_packet_sources_are_digital_business_bits(self):
        for phy in ('reference','program'):
            for operation in (link.protocol,link.amc):
                with self.subTest(phy=phy,operation=operation.__name__), self.assertRaisesRegex(ValueError,'闭环协议请选择数字业务信源'):
                    operation(c.PRESETS['iq_replay']['program'],{'phy':phy})
        p = c.preset(['audio_source','adpcm_encode','mod_qpsk','awgn','demod_qpsk','adpcm_decode','sink'])
        with self.assertRaisesRegex(ValueError,'闭环协议请选择数字业务信源'): link.amc(p,{'phy':'program','coding':'convolutional'})

    def test_capture_failures_trigger_nack_and_exclude_unaligned_llrs(self):
        for key in ('dsss_interference','fhss_antijamming'):
            with self.subTest(preset=key):
                p = copy.deepcopy(c.PRESETS[key]['program'])
                for block in p['blocks']:
                    if block['kind'] in ('rx_code_acquire','rx_hop_sync'): block['params']['threshold']=.99
                    if block['kind']=='complex_awgn': block['params']['snr_db']=-10
                result = link.protocol(p,{'phy':'program','mode':'harq','packets':1,'feedback_loss':0,'max_retries':2})
                self.assertEqual(result['metrics']['transmissions'],3)
                self.assertTrue(all(event['event']=='NACK' for event in result['events']))
                self.assertTrue(all(event['combined_transmissions']==0 for event in result['events']))


if __name__=='__main__': unittest.main()
