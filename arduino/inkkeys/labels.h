/*
 * E-Ink adaptive macro keyboard
 * See https://there.oughta.be/a/macro-keyboard
 *
 * A tiny text renderer for the screen shown at boot when a layout is saved on
 * the keyboard (see standalone.ino). It has no Arduino dependencies, so it can
 * be compiled and checked on a PC as well.
 *
 * Labels use a 3x5 pixel font (uppercase ASCII) drawn at double size: 6x10
 * pixels per character, 8 pixels apart, lines 14 pixels apart. A '|' starts a
 * new line. Like the images from the controller, tiles are rotated by 180°.
 */
#ifndef LABELS_H
#define LABELS_H

#include <stdint.h>
#ifdef __AVR__
  #include <avr/pgmspace.h>
#else
  #define PROGMEM
  #define pgm_read_word(p) (*(p))
#endif

//Bit (row*3 + column) is set for ink, row 0 at the top. Characters 32 (space) to 95 (_).
const uint16_t labelFont[64] PROGMEM = {
  0x0000, 0x2092, 0x002D, 0x5F7D, 0x3C9E, 0x52A5, 0x6AAA, 0x0012, // !"#$%&'
  0x4494, 0x1491, 0x0AA8, 0x05D0, 0x1400, 0x01C0, 0x2000, 0x12A4, //()*+,-./
  0x7B6F, 0x749A, 0x73E7, 0x79A7, 0x49ED, 0x79CF, 0x7BCE, 0x24A7, //01234567
  0x7BEF, 0x79EF, 0x0410, 0x1410, 0x4454, 0x0E38, 0x1511, 0x21A7, //89:;<=>?
  0x636A, 0x5BEA, 0x3AEB, 0x624E, 0x3B6B, 0x72CF, 0x12CF, 0x6B4E, //@ABCDEFG
  0x5BED, 0x7497, 0x2B24, 0x5AED, 0x7249, 0x5BFD, 0x5B6B, 0x2B6A, //HIJKLMNO
  0x12EB, 0x676A, 0x5AEB, 0x388E, 0x2497, 0x7B6D, 0x2B6D, 0x5FED, //PQRSTUVW
  0x5AAD, 0x24AD, 0x72A7, 0x324B, 0x4889, 0x6926, 0x002A, 0x7000, //XYZ[bs]^_
};

const uint8_t LABEL_SCALE = 2;
const uint8_t LABEL_ADVANCE = 8;     //Glyph is 6 pixels wide at LABEL_SCALE 2, plus 2 pixels gap
const uint8_t LABEL_GLYPH_H = 10;
const uint8_t LABEL_LINE = 14;

static uint8_t labelLines(const char* text) {
  uint8_t n = 1;
  for (const char* c = text; *c; c++)
    if (*c == '|') n++;
  return n;
}

//Start and length of line number "line"
static const char* labelLine(const char* text, uint8_t line, uint8_t &len) {
  const char* start = text;
  for (; line > 0 && *start; start++)
    if (*start == '|') line--;
  len = 0;
  while (start[len] && start[len] != '|') len++;
  return start;
}

//True if the pixel at (x, y), seen upright, is ink for text centered in a w x h tile
static bool labelPixel(const char* text, int16_t w, int16_t h, int16_t x, int16_t y) {
  uint8_t lines = labelLines(text);
  int16_t top = (h - (lines * LABEL_LINE - (LABEL_LINE - LABEL_GLYPH_H))) / 2;
  if (y < top) return false;
  uint8_t line = (y - top) / LABEL_LINE;
  uint8_t gy = (y - top) % LABEL_LINE;
  if (line >= lines || gy >= LABEL_GLYPH_H) return false;
  uint8_t len;
  const char* s = labelLine(text, line, len);
  int16_t left = (w - (len * LABEL_ADVANCE - (LABEL_ADVANCE - 3 * LABEL_SCALE))) / 2;
  if (x < left) return false;
  uint8_t ci = (x - left) / LABEL_ADVANCE;
  uint8_t gx = (x - left) % LABEL_ADVANCE;
  if (ci >= len || gx >= 3 * LABEL_SCALE) return false;
  char c = s[ci];
  if (c >= 'a' && c <= 'z') c -= 32;
  if (c < 32 || c > 95) c = '?';
  uint16_t glyph = pgm_read_word(&labelFont[c - 32]);
  return (glyph >> ((gy / LABEL_SCALE) * 3 + gx / LABEL_SCALE)) & 1;
}

//Fills "rows" rows of a w x h tile (w a multiple of 8) for the display, starting at
//panel row "firstRow". The panel shows tiles rotated by 180°, bit 7 is the leftmost
//pixel and a set bit is white.
static void labelRows(uint8_t* buf, const char* text, bool inverted, int16_t w, int16_t h, int16_t firstRow, int16_t rows) {
  int16_t bytesPerRow = w / 8;
  for (int16_t r = 0; r < rows; r++) {
    int16_t py = firstRow + r;
    for (int16_t b = 0; b < bytesPerRow; b++) {
      uint8_t v = 0;
      for (uint8_t bit = 0; bit < 8; bit++) {
        int16_t px = b * 8 + bit;
        bool ink = labelPixel(text, w, h, w - 1 - px, h - 1 - py);
        if (ink == inverted) v |= 0x80 >> bit; //White pixel
      }
      buf[r * bytesPerRow + b] = v;
    }
  }
}

#endif
