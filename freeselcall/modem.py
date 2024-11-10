from _fsk_cffi import ffi, lib

from typing import Callable
import logging
from dataclasses import dataclass
import enum

from .pagecall_magic import get_magic

FDMDV_SCALE = 825

MAX_PAGE_LENGTH = 64
PHASING_PATTERN_THRESHOLD = 0.85
MAX_RX_BUFFER_SIZE_BITS = 10*(12+18)
MAX_RX_BUFFER_SIZE_BITS_PAGE = 10*(12+ 28 + (MAX_PAGE_LENGTH* 2)) # (phasing(12) + paging header/footer + 64*2 words for page mssage) * 10 bits

ASCII_OFFSET = 27 # used for pages

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



SEL_SEL = 0x78     # Selective call
SEL_ID  = 0x7b     # Individual station semi-automatic/automatic service (Codan channel test)
SEL_EOS = 0x7f     # ROS
SEL_MSG = 0x66


SEL_ARQ = 0x75     # Acknowledge Request (EOS)
SEL_PDX = 0x7d     # Phasing DX Position
SEL_PH7 = 0x6f     # Phasing RX-7 position
SEL_PH6 = 0x6e     # RX-6
SEL_PH5 = 0x6d     # RX-5
SEL_PH4 = 0x6c     # RX-4
SEL_PH3 = 0x6b     # RX-3
SEL_PH2 = 0x6a     # RX-2
SEL_PH1 = 0x69     # RX-1
SEL_PH0 = 0x68     # Phasing RX-0 Position

PHASING_PATTERN = [SEL_PDX, SEL_PH5, SEL_PDX, SEL_PH4, SEL_PDX, SEL_PH3, SEL_PDX, SEL_PH2, SEL_PDX, SEL_PH1, SEL_PDX, SEL_PH0]
PHASING_PATTERN_BINARY = [symbol for word in PHASING_PATTERN for symbol in selcall_get_word(word)]

SUPPORTED_FORMATS = [SEL_SEL, SEL_ID]

class CallCategories(enum.Enum):
    RTN = 0x64
    BIZ = 0x6a
    SAFETY = 0x6c
    URGENT = 0x6e
    DISTRESS = 0x70


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
        self.header_snr = None
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
                    if not self.header_snr:
                        self.header_snr = self.snr
                    if self.found_header == False:
                        logging.info(f"Found phasing pattern - {x}")
                    self.found_header = True
                    early_exit = True
                    if self.is_page(self.rx_demodulated_buffer[x+(len(PHASING_PATTERN_BINARY)):]):
                        if not self.is_end_of_page(self.rx_demodulated_buffer[x+(len(PHASING_PATTERN_BINARY)):]):
                            early_exit = False
                            logging.debug("Is likely a page - wait for more data")
                        else:
                            logging.info("found end of page")
                        
                                          
                    if ((x + MAX_RX_BUFFER_SIZE_BITS + len(PHASING_PATTERN_BINARY) <= len(self.rx_demodulated_buffer)) and early_exit) or \
                        (x < self.bytes_per_frame):
                        logging.debug(len(self.rx_demodulated_buffer))
                        logging.info(f"Should have the rest of the packet by now {x}")
                        packet_length = MAX_RX_BUFFER_SIZE_BITS if early_exit else MAX_RX_BUFFER_SIZE_BITS_PAGE
                        logging.debug(packet_length)
                        logging.debug(len(self.rx_demodulated_buffer[x+(len(PHASING_PATTERN_BINARY)):])) #x+packet_length+len(PHASING_PATTERN_BINARY)
                        self.process(self.rx_demodulated_buffer[x+(len(PHASING_PATTERN_BINARY)):]) # x+packet_length+len(PHASING_PATTERN_BINARY)
                        del self.rx_demodulated_buffer[:] # wipe the buffer so we don't decode twice
                        self.header_snr = None # reset SNR
                        return
            if header_found == False:
                if self.found_header:
                    logging.debug("header lost out of buffer")
                    self.header_snr = None
                self.found_header = False
            #logging.debug(self.rx_demodulated_buffer)
            if len(self.rx_demodulated_buffer) > MAX_RX_BUFFER_SIZE_BITS_PAGE:
                del self.rx_demodulated_buffer[0:len(self.rx_demodulated_buffer)-MAX_RX_BUFFER_SIZE_BITS_PAGE]

            #logging.debug(bytes(from_modem))
    def is_page(self, data):
        words = []
        for index in range(0,len(data)-10,10):
            d = 0
            for i in range(0,7):
                d += data[index+i] * 128
                d = d >> 1
            words.append(d)
        if len(words) >= 18:
            if (words[12] == SEL_MSG) or (words[17] == SEL_MSG):
                return True
        return False
    def is_end_of_page(self, data):
        words = []
        
        for index in range(0,len(data)-10,10):
            d = 0
            for i in range(0,7):
                d += data[index+i] * 128
                d = d >> 1
            words.append(d)
        logging.debug(words)
        
        if len(words) >= 18:
            for x in range(0,10): # look back a few words
                if (
                    ( words[-7-x] == SEL_ARQ ) +
                    ( words[-6-x] == SEL_ARQ ) + 
                    ( words[-4-x] == SEL_ARQ ) + 
                    ( words[-2-x] == SEL_ARQ ) + 
                    ( words[-1-x] == SEL_ARQ ) ) > 4:
                    return True
        return False
         
    def process(self, data):
        words = []
        parity_valid = []
        for index in range(0,len(data)-10,10):
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
        logging.debug([f'{x:#02x}' for x in words])
        
        if (
            (words[0] in SUPPORTED_FORMATS) + \
            (words[1] in SUPPORTED_FORMATS) + \
            (words[3] in SUPPORTED_FORMATS) + \
            (words[5] in SUPPORTED_FORMATS)
           ) > 2:
            logging.info("Probably a SelCall!")
            
            if (
                (words[0] == SEL_ID) + \
                (words[1] == SEL_ID) + \
                (words[3] == SEL_ID) + \
                (words[5] == SEL_ID)
            ) > 2:
                chan_test = True
            else:
                chan_test = False
            
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

            category = None
            try:
                if parity_valid[6]:
                    category = CallCategories(words[6]).name
                elif parity_valid[11]:
                    category = CallCategories(words[11]).name
                else:
                    logging.warning("Parity bad for both callcategory words")
            except ValueError:
                logging.warning("Unknown call category")
                if parity_valid[6]:
                    category = words[6]
                if parity_valid[11]:
                    category = words[11]

            sources = set(sources)
            if len(sources) > 1:
                logging.warning(f"More than one source decoded: {sources}")
            if len(sources) == 0:
                logging.warning(f"No sources decoded with correct parity")
            
            logging.debug(f"sources : {sources}")
            
            logging.info(f"SelCall from {sources} to {targets}")

            if ((words[12] == SEL_MSG and parity_valid[12]) or (words[17] == SEL_MSG  and parity_valid[17])):
                logging.debug("Page call")

                # determine length of page
                page_length = None
                for x in range(0, len(words) - 11):
                    count_of_eof = (words[x]  == SEL_ARQ) + \
                    (words[x+5] == SEL_ARQ) + \
                    (words[x+6] == SEL_ARQ) + \
                    (words[x+8] == SEL_ARQ) + \
                    (words[x+10] == SEL_ARQ) + \
                    (words[x+11] == SEL_ARQ)
                    #logging.debug(count_of_eof)
                    if (count_of_eof) > 3:
                        page_length =  6+((x - 28)//2) # 28 = fixed frame parts, then divide by 2 as each char repeated twice + 6 for the length of the eof
                        logging.debug(f"Page length {page_length}")
                        break
                if not page_length:
                    logging.warning("Could not find end of page - giving up")
                if page_length:
                    page = [None]*page_length
                    for x in range(0, (page_length)):
                        if not parity_valid[x*2+16]:
                            logging.warning(f"parity invalid for word in page:{x+16}")
                        else:
                            page[x] = chr(words[x*2+16] + ASCII_OFFSET)
                        
                        if not parity_valid[x*2+21]:
                            logging.warning(f"parity invalid for word in page:{x+21}")
                            if not page[x]:
                                logging.warning(f"No good data for page index {x}, filling in with �")
                                page[x] = "�"
                        else:
                            b_char = chr(words[x*2+21] + ASCII_OFFSET)
                            if page[x] and page[x] != b_char:
                                logging.warning(f"two different good parity decodes for word {x+16}/{x+21} : {page[x]}/{b_char}")
                                #print(page)
                            else:
                                page[x] = chr(words[x*2+21] + ASCII_OFFSET)
                    page = "".join(page)
                    logging.debug(f"Page: {page}")
                    self.callback(
                        {
                            "source": [f"{x:04}" for x in sources],
                            "target": [f"{x:04}" for x in targets],
                            "message": "Page",
                            "chantest": chan_test,
                            "page": page,
                            "words": words,
                            "snr": self.header_snr,
                            "category": category
                        }
                    )
                    return
                    
            if self.callback:
                self.callback(
                    {
                        "source": [f"{x:04}" for x in sources],
                        "target": [f"{x:04}" for x in targets],
                        "message": "ChanTest" if chan_test else "SelCall",
                        "chantest": chan_test,
                        "words": words,
                        "snr": self.header_snr,
                        "category": category
                    }
                )
        else:
            logging.warning(f"Not known selcall type : {words}")
        

    def sel_call_modulate(self, source, target, category=CallCategories.RTN, channel_test=False, page=None) -> bytes:
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

        ID_TYPE = SEL_ID if channel_test else SEL_SEL

        if page:
            page = page[:64]
            callmsg = [None] * (28 + (len(page)* 2))
                               # 0        1      2          3       4      5         6                7      8        9       10          11             12      13       14              15       16               17             18              19
            callmsg[0:20] = [ID_TYPE, ID_TYPE, addr_B1, ID_TYPE, addr_B2, ID_TYPE, category.value, addr_B1, addr_A1, addr_B2, addr_A2, category.value, SEL_MSG, addr_A1, category.value, addr_A2,  None,         SEL_MSG,          None,      category.value   ]
            
            # add the message data
            for x in range(0, len(page)):
                callmsg[(x*2)+16] = ord(page[x])-ASCII_OFFSET
                callmsg[(x*2)+21] = ord(page[x])-ASCII_OFFSET
            
            magic_bytes = get_magic(target, source, category.value, ID_TYPE)

            callmsg[16 + len(page)*2 ]    = SEL_ARQ
            callmsg[16 + len(page)*2 +2]  = magic_bytes[0]
            callmsg[16 + len(page)*2 +4]  = magic_bytes[1] 
            callmsg[16 + len(page)*2 +5]  = SEL_ARQ
            callmsg[16 + len(page)*2 +7]  = magic_bytes[0]
            callmsg[16 + len(page)*2 +6]  = SEL_ARQ
            callmsg[16 + len(page)*2 +8]  = SEL_ARQ
            callmsg[16 + len(page)*2 +9]  = magic_bytes[1] 
            callmsg[16 + len(page)*2 +10] = SEL_ARQ
            callmsg[16 + len(page)*2 +11] = SEL_ARQ

        else:
            callmsg = [ID_TYPE, ID_TYPE, addr_B1, ID_TYPE, addr_B2, ID_TYPE, category.value, addr_B1, addr_A1, addr_B2, addr_A2, category.value, SEL_ARQ, addr_A1, SEL_ARQ, addr_A2, SEL_ARQ, SEL_ARQ]
       
        callmsg_bits = [symbol for word in callmsg for symbol in selcall_get_word(word)]

        logging.debug(f"output words: {callmsg}")

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
        self.sel_call_modulate = self.modem.sel_call_modulate
