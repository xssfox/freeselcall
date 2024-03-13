from _fsk_cffi import ffi, lib

from typing import Callable
import logging
from dataclasses import dataclass

FDMDV_SCALE = 825


PHASING_PATTERN_THRESHOLD = 0.85
MAX_RX_BUFFER_SIZE_BITS = 10*(12+18)


def selcall_get_word(value) -> list:
    """
    Creates a list of 1,0's which is the 10bit (7 bit data, 3 bit parity) word

        A CCIR 493-4 word consists of a 7-bit word number (0-127), and a 3-bit parity,
    which is the number of 0's in the word.
    The 7-bit word number is send LSB first, then the parity MSB first.
    """
    data = list()
    data += [int(x) for x in format(value, '07b')][::-1]
    zero_count = data.count(0)
    data += [int(x) for x in format(zero_count, '03b')]
    return data



SEL_SEL = 120     # Selective call
SEL_ID  = 123     # Individual station semi-automatic/automatic service (Codan channel test)
SEL_EOS = 127     # ROS
SEL_RTN = 100     # Routine call
SEL_ARQ = 117     # Acknowledge Request (EOS)
SEL_PDX = 125     # Phasing DX Position
SEL_PH7 = 111     # Phasing RX-7 position
SEL_PH6 = 110     # RX-6
SEL_PH5 = 109     # RX-5
SEL_PH4 = 108     # RX-4
SEL_PH3 = 107     # RX-3
SEL_PH2 = 106     # RX-2
SEL_PH1 = 105     # RX-1
SEL_PH0 = 104     # Phasing RX-0 Position

PHASING_PATTERN = [SEL_PDX, SEL_PH5, SEL_PDX, SEL_PH4, SEL_PDX, SEL_PH3, SEL_PDX, SEL_PH2, SEL_PDX, SEL_PH1, SEL_PDX, SEL_PH0]
PHASING_PATTERN_BINARY = [symbol for word in PHASING_PATTERN for symbol in selcall_get_word(word)]

class Modem():
    def __init__(self, callback=None):

        self.modem = lib.fsk_create_hbr(
            8000,
            100, # 100 baud
            2,
            8, # oversampling
            lib.FSK_DEFAULT_NSYM,
            1700,
            170
        )

        lib.fsk_set_freq_est_limits(self.modem, 1000, 2500)
        lib.fsk_set_freq_est_alg(self.modem, 1) # use tone spacing

        self.modem_stats = lib.modem_stats_open

        self.buffer = bytearray()
        self.rx_demodulated_buffer = bytearray()
        self.callback = callback
        self.bytes_per_frame
        self.found_header = False
        logging.debug("meow")

    @property
    def version(self) -> int:
        return 0

    @property
    def nin(self) -> int:
        """
        Number of bytes that the modem is expecting to process
        """
        return lib.fsk_nin(self.modem) 
    
    @property
    def bytes_per_frame(self) -> int:
        """
        Max number of bytes returned for each frame of audio sent. Used to build buffers.
        """
        bytes_per_frame = self.modem.Nbits
        return bytes_per_frame
    
    @property
    def snr(self) -> float:
        """
        Receivers SNR reported by the modem
        """

        stats = ffi.new("struct MODEM_STATS *")
        lib.fsk_get_demod_stats(self.modem, stats)
        return stats.snr_est
    
    
    def write(self, data: bytes) -> None:
        """
        Feed in audio bytes.
        """
        # add data to our internal buffer
        self.buffer += data

        # if we have enough data run the demodulator
        while (nin := self.nin) * 2 <= len(self.buffer):

            # setup the memory location where audio samples will be read from
            to_modem = ffi.new("COMP[]", nin)
            for x in range(0,nin):
                # modbuf[i].real = ((float)rawbuf[i]) / FDMDV_SCALE; FDMDV_SCALE = 825
                # modbuf[i].imag = 0.0;
                
                sample = self.buffer[x*2:(x*2)+2]
                
                to_modem[x].real = int.from_bytes(sample, byteorder="little") / FDMDV_SCALE
                #print(to_modem[x].real,end=", ")
                to_modem[x].imag = 0
            #logging.debug(to_modem)
            # remove the loaded samples from the buffer
            del self.buffer[:nin * 2] 
            # setup a location to put the results
            from_modem = ffi.new("uint8_t this_name_doesnt_matter[]", self.bytes_per_frame)

            # run the demodulator
            lib.fsk_demod(self.modem,from_modem,to_modem)
            
            # log_line = ""
            # output_log = False
            # for x in bytes(from_modem):
            #     if x:
            #         log_line += "1"
            #         output_log = True
            #     else:
            #         log_line += "0"
            # if output_log:
            #     logging.debug(log_line)

            self.rx_demodulated_buffer += bytes(from_modem)

            header_found = False
            for x in range(len(self.rx_demodulated_buffer)-len(PHASING_PATTERN_BINARY)-1):
                if (list(self.rx_demodulated_buffer[x:x+20]) == [0,1]*10 or \
                list(self.rx_demodulated_buffer[x:x+20]) == [1,0]*10) and self.snr > 10:
                    logging.debug("Preamble detected")
                    self.callback(
                        {
                            "message": "Preamble",
                            "snr": self.snr 
                        }
                    )
                    break
            for x in range(len(self.rx_demodulated_buffer)-len(PHASING_PATTERN_BINARY)-1):
                matches = 0
                
                for y in range(len(PHASING_PATTERN_BINARY)):
                    if self.rx_demodulated_buffer[x+y] == PHASING_PATTERN_BINARY[y]:
                        matches += 1
                if matches/len(PHASING_PATTERN_BINARY) > PHASING_PATTERN_THRESHOLD:
                    logging.debug(f"Phasing pattern match: {matches/len(PHASING_PATTERN_BINARY)*100}%")


                if (self.rx_demodulated_buffer[x:x+len(PHASING_PATTERN_BINARY)] == bytearray(PHASING_PATTERN_BINARY)) or \
                    matches/len(PHASING_PATTERN_BINARY) > PHASING_PATTERN_THRESHOLD:
                    header_found = True
                    self.header_snr = self.snr
                    if self.found_header == False:
                        logging.info(f"Found phasing pattern - {x}")
                    self.found_header = True
                    if x < self.bytes_per_frame:
                        logging.info("Should have the rest of the packet by now")
                        logging.debug(self.rx_demodulated_buffer[x+(len(PHASING_PATTERN_BINARY)):x+MAX_RX_BUFFER_SIZE_BITS])
                        self.process(self.rx_demodulated_buffer[x+(len(PHASING_PATTERN_BINARY)):x+MAX_RX_BUFFER_SIZE_BITS])
            if header_found == False:
                if self.found_header:
                    logging.debug("header lost out of buffer")
                self.found_header = False
            #logging.debug(self.rx_demodulated_buffer)
            if len(self.rx_demodulated_buffer) > MAX_RX_BUFFER_SIZE_BITS:
                del self.rx_demodulated_buffer[0:len(self.rx_demodulated_buffer)-MAX_RX_BUFFER_SIZE_BITS]

            #logging.debug(bytes(from_modem))

         
    def process(self, data):
        words = []
        parity_valid = []
        for index in range(0,len(data),10):
            # for i in range(0,10):
            #     print(data[index+i], end="")
            # print()
            d = 0
            p = 0
            calc_p = 0
            for i in range(0,7):
                d += data[index+i] * 128
                d = d >> 1
                if not data[index+i]:
                    calc_p += 1
            for i in range(7,10):
                p = p << 1
                p += data[index+i]
            if calc_p != p:
                parity_valid.append(False)
                logging.debug(f"parity failed for word index {index}")
                logging.debug(f"calc_p: {calc_p}")
                logging.debug(f"p: {p}")
            else:
                parity_valid.append(True)
            words.append(d)
        logging.debug("Words: ")
        logging.debug(words)
        if (
            (words[0] == SEL_SEL) + \
            (words[1] == SEL_SEL) + \
            (words[3] == SEL_SEL) + \
            (words[5] == SEL_SEL)
           ) > 2:
            logging.info("Probably a SelCall!")
        
            targets = []

            if parity_valid[2] and parity_valid[4]:
                targets.append(words[2]*100 + words[4])
            if parity_valid[7] and parity_valid[9]:
                targets.append(words[7]*100 + words[9])
            if parity_valid[2] and parity_valid[9]:
                targets.append(words[2]*100 + words[9])
            if parity_valid[7] and parity_valid[4]:
                targets.append(words[7]*100 + words[4])

            targets = set(targets)
            if len(targets) > 1:
                logging.warning(f"More than one target decoded with correct parity: {targets}")
            logging.debug(f"targets : {targets}")
            
            if len(targets) == 0:
                logging.warning(f"No targets decoded with correct parity")

            sources = []
            if parity_valid[8] and parity_valid[10]:
                sources.append(words[8]*100 + words[10])
            if parity_valid[13] and parity_valid[15]:
                sources.append(words[13]*100 + words[15])
            if parity_valid[8] and parity_valid[15]:
                sources.append(words[8]*100 + words[15])
            if parity_valid[13] and parity_valid[10]:
                sources.append(words[13]*100 + words[10])

            sources = set(sources)
            if len(sources) > 1:
                logging.warning(f"More than one source decoded: {sources}")
            if len(sources) == 0:
                logging.warning(f"No sources decoded with correct parity")
            
            logging.debug(f"sources : {sources}")
            
            logging.info(f"SelCall from {sources} to {targets}")
            if self.callback:
                self.callback(
                    {
                        "source": [f"{x:04}" for x in sources],
                        "target": [f"{x:04}" for x in targets],
                        "message": "SelCall",
                        "words": words,
                        "snr": self.header_snr 
                    }
                )
        

    def sel_call_modulate(self, source, target) -> bytes:
        """
        Modulates a selcall into audio samples (also bytes)
        """
        packet = list()

        # Preamble
        for k in range(0,100*6//2):
            packet.append(k % 2)
        #logging.debug(packet)

        packet += PHASING_PATTERN_BINARY

        addr_A1 = (source//100)%100
        addr_A2 = (source%100)
        addr_B1 = (target//100)%100
        addr_B2 = target%100

        callmsg = [SEL_SEL, SEL_SEL, addr_B1, SEL_SEL, addr_B2, SEL_SEL, SEL_RTN, addr_B1, addr_A1, addr_B2, addr_A2, SEL_RTN, SEL_ARQ, addr_A1, SEL_ARQ, addr_A2, SEL_ARQ, SEL_ARQ]

        callmsg_bits = [symbol for word in callmsg for symbol in selcall_get_word(word)]

        #logging.debug(callmsg_bits)
        packet += (callmsg_bits)
        #logging.debug(len(packet))

        packet_bytes = bytearray(packet)

        logging.debug(f"output packet: {packet}")

        output = bytes()
        while(packet_bytes):
            # uint8_t
            packet_buffer = ffi.from_buffer("uint8_t[]", packet_bytes[0:self.modem.Nbits])
            #logging.debug(bytes(packet_buffer))
            del packet_bytes[0:self.modem.Nbits]
            mod_buffer = ffi.new("float modbuf[]", self.modem.N)

            lib.fsk_mod(self.modem, mod_buffer, packet_buffer, min(self.modem.Nbits, len(packet_buffer)))
            
            # I'm not proud of this next part
            output_list = [int(x / 2 * 32767).to_bytes(byteorder="little", length=2, signed=True) for x in list(mod_buffer) ]
            for item in output_list:
                output += item
        return output

class  FreeselcallRX():
    def __init__(self, callback=None):
        self.callback = callback

        self.modem = Modem(callback=callback)

        self.sample_rate = 8000
        
    def write(self, data: bytes) -> None:
        """
        Accepts bytes of data that will be read by the modem and demodulated
        """
        self.modem.write(data)



class FreeselcallTX():
    def __init__(self):
        self.modem = Modem()
        self.sample_rate = 8000
    def sel_call_modulate(self, source, target):
        return self.modem.sel_call_modulate(source, target)