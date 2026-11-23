"""Cross-language wire format, source splitting, USB ordering and frame outcomes."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import communications as comm, communication_board_codegen as codegen, communication_codecs
from src import communication_board_link as link, communication_board_pair as pair
from src.communication_board_api import source_zip
from test_communication_board_codegen import Pin, UartPeer, python_records


def generate(preset, tx_board, tx_lang, rx_board, rx_lang):
    choices = {'tx': {'board':tx_board, 'language':tx_lang}, 'rx': {'board':rx_board, 'language':rx_lang}}
    return codegen.generate(comm.PRESETS[preset]['program'], tx_lang, tx_board, choices)


class MemoryPort(io.BytesIO):
    def __init__(self, records):
        super().__init__(records)
        self.started = False

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.started = True
        self.command = data
        return len(data)

    def read(self, count):
        assert self.started
        return super().read(count)

    @property
    def in_waiting(self):
        return len(self.getvalue())-self.tell()


def run_python(ep, wire, nonce):
    scope = {'__name__':'qa'}
    exec(ep['files']['main.py'],scope)
    buffer = bytearray(wire.read_bytes()) if wire.exists() else bytearray()
    class UART:
        def __init__(self, *args, **kw):
            pass
        def any(self):
            return 0
        def read(self, count):
            n=min(count,3)
            chunk=buffer[:n]
            del buffer[:n]
            return bytes(chunk) or None
        def write(self, data):
            wire.write_bytes(data)
            return len(data)
    with patch.dict(sys.modules, machine=type('Machine', (), {'UART':UART,'Pin':Pin})):
        stdin = io.StringIO(f"RUN {ep['artifact_id']} {nonce}\n")
        with patch('sys.stdin', stdin), contextlib.redirect_stdout(io.StringIO()) as console:
            scope['serve']()
    return console.getvalue().encode()


# Replace just the pins and USB console with host streams, keeping the generated
# frame encoder, parser, block logic, role identity and telemetry byte-for-byte.
HOST_UART = """
#include <cstdlib>
static FILE *wire;
static void link_open(unsigned) { wire = std::fopen(std::getenv("RS_WIRE"), "rb"); }
static void link_write(const uint8_t *data, size_t size) {
    if (wire) std::fclose(wire);
    wire=std::fopen(std::getenv("RS_WIRE"),"wb");
    std::fwrite(data,1,size,wire); std::fclose(wire); wire=nullptr;
}
static bool link_read(uint8_t &byte, unsigned) { return wire && std::fread(&byte,1,1,wire)==1; }
"""


def run_cpp(ep, wire, nonce):
    root = wire.parent/ep['artifact_id']
    exe = root/('board.exe' if os.name=='nt' else 'board')
    if not exe.exists():
        root.mkdir()
        (root/'main.cpp').write_text(ep['files'][ep['entry_file']],encoding='utf-8')
        (root/'board_uart.hpp').write_text(HOST_UART)
        if ep['board']=='esp32s3':
            (root/'esp_console.hpp').write_text('inline void start_console() {}')
            (root/'entry.cpp').write_text('extern "C" void app_main(); int main(){app_main();}')
            sources=['main.cpp','entry.cpp']
        else:
            (root/'pico').mkdir()
            (root/'hardware').mkdir()
            (root/'pico/stdlib.h').write_text('inline void stdio_init_all() {}')
            (root/'hardware/uart.h').write_text('')
            sources=['main.cpp']
        subprocess.run(['g++','-std=c++17','-I.',*sources,'-o',exe.name],cwd=root,check=True,timeout=60)
    return subprocess.check_output([str(exe)],input=f"RUN {ep['artifact_id']} {nonce}\n".encode(),
                                   env={**os.environ,'RS_WIRE':str(wire)},timeout=5)


class LinkTests(unittest.TestCase):
    def test_esp_single_board_regression(self):
        for name, entry in comm.PRESETS.items():
            if not name.startswith('board_') or name.startswith('board_link_'):
                continue
            with self.subTest(name=name):
                p = entry['program']
                esp = codegen.generate(p,'micropython','esp32s3')
                self.assertEqual(esp['expected'],codegen.generate(p,'cpp','pico')['expected'])
                peer=UartPeer('echo')
                records=python_records(esp,peer)
                self.assertEqual(records[-1]['metrics'],esp['expected']['metrics'])
                if esp['experiment']=='uart':
                    self.assertEqual((peer.config[0],peer.config[5:7]),(1,(17,18)))

    def test_frame_crc_and_valid_bits(self):
        data=np.arange(127,dtype=np.uint8)%2
        frame=link.encode_frame(data,0x1234)
        self.assertEqual(frame[:7],b'RS\x01\x12\x34\x00\x7f')
        np.testing.assert_array_equal(link.decode_frame(frame,0x1234),data)
        crc=communication_codecs.crc(np.unpackbits(np.frombuffer(frame[:-2],dtype=np.uint8)),16)
        self.assertEqual(frame[-2:],np.packbits(crc).tobytes())
        for broken,seq in [(frame[:-1],0x1234),(frame,0x1235),(frame[:-2]+b'aa',0x1234)]:
            with self.assertRaises(ValueError): link.decode_frame(broken,seq)

    def test_independent_projects_and_source_spans(self):
        for tx in codegen.BOARDS:
            for rx in codegen.BOARDS:
                for tx_lang in codegen.LANGUAGES:
                    for rx_lang in codegen.LANGUAGES:
                        project=generate('board_link_text',tx,tx_lang,rx,rx_lang)
                        with ZipFile(io.BytesIO(source_zip(project).body)) as archive:
                            self.assertIsNone(archive.testzip())
                            for role,ep in project['endpoints'].items():
                                self.assertEqual(json.loads(archive.read(role+'/experiment.json'))['role'],role)
                                source=archive.read(role+'/'+ep['entry_file']).decode()
                                self.assertIn(ep['artifact_id'],source)
                                for key,span in ep['source_map'].items():
                                    self.assertIn(key,source.splitlines()[span['start']-1])
                                if role=='rx':
                                    self.assertNotIn('0xe4, 0xbd',source)
                                    self.assertNotIn('bit_pattern [',source)
                                    self.assertNotIn('transmit_frame(', source)
                                else:
                                    self.assertNotIn('receive_frame(', source)
        with self.assertRaises(codegen.BoardCodeError):
            codegen.generate(comm.PRESETS['board_link_pn']['program'],'cpp','pico')

    def test_both_languages_on_the_wire(self):
        runners={'micropython':run_python}
        if shutil.which('g++'): runners['cpp']=run_cpp
        nonce='aabb1234'
        with tempfile.TemporaryDirectory() as tmp:
            wire=Path(tmp)/'wire.bin'
            for name in ('board_link_text','board_link_pn','board_link_hamming'):
                for tx_lang,send in runners.items():
                    for rx_lang,receive in runners.items():
                        for tx,rx in [('pico','esp32s3'),('esp32s3','pico_w')]:
                            project=generate(name,tx,tx_lang,rx,rx_lang)
                            eps=project['endpoints']
                            with self.subTest(name=name,tx=tx,rx=rx,langs=(tx_lang,rx_lang)):
                                sent=send(eps['tx'],wire,nonce)
                                expected=project['expected']['nodes'][project['bridge']]
                                self.assertEqual(wire.read_bytes(),link.encode_frame(expected,0x1234))
                                received=receive(eps['rx'],wire,nonce)
                                report=pair.run_ports(project,MemoryPort(sent),MemoryPort(received),nonce)
                                self.assertTrue(report['matches_reference'])
                                self.assertEqual(report['metrics'],project['expected']['metrics'])
                                self.assertTrue(report['frame']['crc_ok'])
                                self.assertEqual(report['syndromes'],project['expected']['syndromes'])

    def test_receiver_faults_and_usb_start_order(self):
        nonce='00010042'
        with tempfile.TemporaryDirectory() as tmp:
            wire=Path(tmp)/'wire.bin'
            for lang in (('cpp','micropython') if shutil.which('g++') else ('micropython',)):
                project=generate('board_link_pn','pico','micropython','esp32s3',lang)
                eps=project['endpoints']; sent=run_python(eps['tx'],wire,nonce)
                good=wire.read_bytes()
                bits=link.decode_frame(good,0x42)
                bad=bytearray(good);bad[-3]^=0x10
                cases={'crc_error':bad,'sequence_error':link.encode_frame(bits,0x43),'length_error':link.encode_frame(bits[:-1],0x42),
                       'timeout':good[:5],'frame_error':b'ZZ'+good[2:],'ok':link.encode_frame(bits^1,0x42)}
                for status,frame in cases.items():
                    with self.subTest(lang=lang,status=status):
                        wire.write_bytes(frame)
                        runner=run_python if lang=='micropython' else run_cpp
                        rx_port=MemoryPort(runner(eps['rx'],wire,nonce))
                        class Tx(MemoryPort):
                            def write(inner, data):
                                self.assertTrue(rx_port.started)
                                self.assertGreater(rx_port.tell(),0)
                                return super(Tx,inner).write(data)
                        report=pair.run_ports(project,Tx(sent),rx_port,nonce)
                        self.assertEqual(report['status'],status)
                        self.assertFalse(report['matches_reference'])
                        self.assertEqual(report['metrics']['ber'],1 if status=='ok' else None)
                        if status in ('ok','crc_error','sequence_error'):
                            self.assertEqual(report['frame']['crc_ok'], status!='crc_error')
                            self.assertEqual(report['frame']['rx_sequence'], 0x43 if status=='sequence_error' else 0x42)
                            self.assertEqual(len(report['frame']['received']),127)
                        if status!='ok':
                            self.assertNotIn(project['bridge'],report['nodes'])
                            self.assertEqual(report['metrics']['lost_frames'],1)


if __name__ == '__main__':
    unittest.main()
