from .modem import  FreeselcallRX,  FreeselcallTX
from . import audio
from .web import Server
from .shell import FreeselcallShell
import logging
import configargparse
import time
from . import rigctl
import datetime
import traceback
from . import chan_test_tune
from prompt_toolkit.formatted_text import HTML, to_formatted_text

logging.basicConfig()

#flask likes to log in RED
import re
ansi_escape = re.compile(r'''
    \x1B  # ESC
    (?:   # 7-bit C1 Fe (except CSI)
        [@-Z\\-_]
    |     # or [ for CSI, followed by a control sequence
        \[
        [0-?]*  # Parameter bytes
        [ -/]*  # Intermediate bytes
        [@-~]   # Final byte
    )
''', re.VERBOSE)

def main():
    p = configargparse.ArgParser(default_config_files=['~/.freeselcall.conf'], config_file_parser_class=configargparse.DefaultConfigFileParser)
    p.add('-c', '-config', required=False, is_config_file=True, help='config file path')

    p.add('--no-cli', action='store_true', env_var="FREESELCALL_NO_CLI")
    p.add('--list-audio-devices', action='store_true', default=False)

    p.add('--log-level', type=str, default="INFO", env_var="FREESELCALL_LOG_LEVEL", choices=logging._nameToLevel.keys())

    p.add('--input-device', type=str, default=None, env_var="FREESELCALL_INPUT_DEVICE")
    p.add('--output-device', type=str, default=None, env_var="FREESELCALL_OUTPUT_DEVICE")
    p.add('--output-volume', type=float, default=-3, env_var="FREESELCALL_OUTPUT_DB", help="in db. postive = louder, negative = quiter")

    p.add('--rigctld-port', type=int, default=4532, env_var="FREESELCALL_RIGTCTLD_PORT", help="TCP port for rigctld - set to 0 to disable rigctld support")
    p.add('--rigctld-selcall-commands', type=str, default="L SQL 0", env_var="FREESELCALL_RIGTCTLD_COMMAND", help="Commands to send the rigctl server - for example 'L SQL 0' on ICOM will disable squelch when selcall is received")
    p.add('--rigctld-pretx', type=str, default="M PKTLSB 3600", env_var="FREESELCALL_RIGTCTLD_PRETX_COMMAND", help="Commands to send the rigctl server before TXing (PTT already included)")
    p.add('--rigctld-posttx', type=str, default="M LSB 3600", env_var="FREESELCALL_RIGTCTLD_POSTTX_COMMAND", help="Commands to send the rigctl server after TXing")
    p.add('--rigctld-host', type=str, default="localhost", env_var="FREESELCALL_RIGTCTLD_HOST", help="Host for rigctld")
    p.add('--ptt-on-delay-ms', type=int, default=100, env_var="FREESELCALL_PTT_ON_DELAY_MS", help="Delay after triggering PTT before sending data")
    p.add('--ptt-off-delay-ms', type=int, default=100, env_var="FREESELCALL_PTT_OFF_DELAY_MS", help="Delay after sending data before releasing PTT")

    p.add('--id', type=int, default=1234, env_var="FREESELCALL_ID", help="ID to notify of selcall and used to send selcall")
    p.add('--no-chan-test', action='store_true', env_var="FREESELCALL_NO_CHAN_TEST", help="Disables automatic replying to channel tests")

    p.add('--no-web', action='store_true', env_var="FREESELCALL_NO_WEB")
    p.add('--web-host', type=str, default="127.0.0.1", env_var="FREESELCALL_WEB_HOST")
    p.add('--web-port', type=int, default=5001, env_var="FREESELCALL_WEB_PORT")
    
    options = p.parse_args()

    logger = logging.getLogger()
    logger.setLevel(level=options.log_level)
    logging.debug("Starting")


    class LogHandler(logging.StreamHandler):
        shell = None
        def __init__(self):
            super().__init__()
            self.log_buffer = ""
        def emit(self, record):
            message_time = str(datetime.datetime.now())
            message = self.format(record)
            #record.msg = str(record.msg)
            for message in message.split("\n"):
                message = ansi_escape.sub('', message)
                if record.name == "root" and record.module == "__main__":
                    msg = HTML(f"{message_time}: <log.{record.levelname.lower()}.msg>{{}}</log.{record.levelname.lower()}.msg>\n").format(message).value
                else:
                    msg = HTML(f"{message_time}:<log.{record.levelname.lower()}.name>{{}}</log.{record.levelname.lower()}.name>").format(record.name).value
                    msg += HTML(f":<log.{record.levelname.lower()}.module>{{}}</log.{record.levelname.lower()}.module>").format(record.module).value
                    msg += HTML(f": <log.{record.levelname.lower()}.msg>{{}}</log.{record.levelname.lower()}.msg>\n").format(message).value

            if options.no_cli:
                print(self.format(record))
            else:
                if not self.shell:
                    print(self.format(record))
                    self.log_buffer += msg
                else:
                    self.shell.add_text(msg)

        

    while logger.hasHandlers(): # remove existing handlers
        logger.removeHandler(logger.handlers[0])
    log_handler = LogHandler()

    log_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(module)s: %(message)s"))
    logger.addHandler(log_handler)


    if options.list_audio_devices:
        print(
            audio.devices
        )
    else:
        modem_tx =  FreeselcallTX()
        logging.info(f"Initialised TX freeselcall Modem - version: {modem_tx.modem.version}")
        def tx(arg, category, chan_test=False, page=None):
            "Performs a selcall - example: selcall 1234"
            mod_out = modem_tx.sel_call_modulate(options.id,int(arg), category, chan_test, page=page)
            if not options.no_web:
                        web.send_log(
                            {
                                "source":options.id,
                                "target":int(arg),
                                "category": category.name,
                                "chan_test": chan_test,
                                "page": page
                            }
                        )
            output_device.write(mod_out)


        def rx(data):
            try:
                if data['message'] in ["SelCall","ChanTest"]:
                    if not options.no_web:
                        web.rx(data)
                    if not options.no_cli: 
                            cat = "CHANTEST" if data["message"] == "ChanTest" else data['category']
                            shell.add_text(
                                HTML("<chat.callsign>&lt;{}&gt;</chat.callsign> -> <chat.callsign>&lt;{}&gt;</chat.callsign> [{}] <chat.message>{}</chat.message>\n").format(", ".join(data['source']), ", ".join(data['target']),cat, data['message']).value
                            )
                    else:
                        print(f"\n<{', '.join(data['source'])}> {', '.join(data['target'])} - {data['message']}")
                    if options.rigctld_selcall_commands and options.rigctld_port != 0 and f"{options.id:04}" in data['target']:
                        logging.debug(f"Sending rig command: {options.rigctld_selcall_commands}")
                        rig_output = rig.send_command(options.rigctld_selcall_commands.encode())
                        logging.debug(f"Rigctl sent")
                        logging.info(f"Rigctl output: {rig_output}")
                if data['message'] == "Preamble":
                    if not options.no_web:
                        web.preamble(data)
                if not options.no_chan_test and "chantest" in data and data['chantest'] == True and f"{options.id:04}" in data['target']:
                    logging.info("Sending back chan test.")
                    output_device.write_raw(chan_test_tune.samples)
                if data['message'] == "Page":
                    if not options.no_web:
                        web.rx(data)
                    if not options.no_cli: 
                            shell.add_text(
                                HTML("<chat.callsign>&lt;{}&gt;</chat.callsign> -> <chat.callsign>&lt;{}&gt;</chat.callsign> [{}] <chat.message>{}</chat.message>\n").format(", ".join(data['source']), ", ".join(data['target']),data['category'], data['page']).value)
                    else:
                        print(f"\n<{', '.join(data['source'])}> {', '.join(data['target'])} - {data['page']}")
            except:
                logging.critical(
                    traceback.format_exc()
                )



        modem_rx =  FreeselcallRX(callback=rx)
        logging.info(f"Initialised RX Freeselcall Modem - version: {modem_rx.modem.version}")

        input_device_name_or_id = options.input_device
        output_device_name_or_id = options.output_device

        try:
            input_device_name_or_id = int(input_device_name_or_id)
            output_device_name_or_id = int(output_device_name_or_id)
        except:
            pass
        
        if options.rigctld_port != 0:
            rig = rigctl.Rigctld(hostname=options.rigctld_host, port=options.rigctld_port)
            logging.info(f"Initialised Rigctl at {options.rigctld_host}:{options.rigctld_port}")
            def ptt_trigger():
                logging.debug(f"Sending pre rig message: {options.rigctld_pretx}")
                result = rig.send_command(options.rigctld_pretx.encode())
                logging.debug(f"Result of pre rig message: {result}")
                rig.ptt_enable()
            def ptt_release():
                logging.debug(f"Sending post rig message: {options.rigctld_posttx}")
                result = rig.send_command(options.rigctld_posttx.encode())
                logging.debug(f"Result of post rig message: {result}")
                rig.ptt_disable()
        else:
            ptt_trigger = None
            ptt_release = None
        
        input_device = audio.InputDevice(modem_rx.write, modem_rx.sample_rate, name_or_id=input_device_name_or_id)
        logging.info(f"Initialised Input Audio: {input_device.device.name}")
        output_device = audio.OutputDevice(
            modem_rx.sample_rate,
            modem = modem_tx,
            name_or_id=output_device_name_or_id,
            ptt_release=ptt_release,
            ptt_trigger=ptt_trigger,
            ptt_on_delay_ms=options.ptt_on_delay_ms,
            ptt_off_delay_ms=options.ptt_off_delay_ms,
            db=options.output_volume
        )
        logging.info(f"Initialised Output Audio: {output_device.device.name}")
        if not options.no_web:
            web = Server(options.web_host, options.web_port, tx, options.id)
            web.start()
        try:
            if not options.no_cli:
                logging.debug(f"Starting shell")
                shell = FreeselcallShell(modem_rx, modem_tx
                , output_device, input_device, p, options, log_handler.log_buffer)
                log_handler.shell = shell
                shell.run()
            else:
                while 1:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            log_handler.shell = None
            if "rig" in locals():
                rig.ptt_disable()
            input_device.close()
            output_device.close()
if __name__ == '__main__':
    main()