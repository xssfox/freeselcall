import unittest

try:
    from .pagecall_magic import get_magic
except:
     from pagecall_magic import get_magic


class TestPagecallMagic(unittest.TestCase):

    # These test were taken from on air recording of my Codan 9323

    def test_1234_7177(self):
        self.assertEqual(get_magic(1234,7177), (0x41, 0x17))

    def test_1235_7178(self):
        self.assertEqual(get_magic(1235,7178), (0x47, 0x5c))

    def test_1_1(self):
        self.assertEqual(get_magic(1,1), (0x2b, 0x41))

    def test_1_2(self):
        self.assertEqual(get_magic(1,2), (38, 25))

    def test_1_3(self):
        self.assertEqual(get_magic(1,3), (88, 85))
    def test_1_9999(self):
        self.assertEqual(get_magic(9999,1), (74, 80))
    def test_3_1(self):
        self.assertEqual(get_magic(3,1), (26, 53))

    def test_999_9999(self): # this forces a negative number into the to_code check
        self.assertEqual(get_magic(999,9999), (0x32, 0x2a))

    def test_6969_420(self):
        self.assertEqual(get_magic(6969,420), (0x14, 0x63))

    def test_8888_2222(self):
        self.assertEqual(get_magic(8888,2222), (0x48, 0x51))
    def test_888_2222(self):
        self.assertEqual(get_magic(888,2222), (61, 23))


if __name__ == '__main__':
    unittest.main()