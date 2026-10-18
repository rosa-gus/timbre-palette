"""rosa-reticle 0.1.0: spatial coverage, tonal behavior, and transport contracts."""

import unittest

from PIL import Image, ImageStat

from scripts.rosa_reticle import (BAYER_4, pair_quantized, pair_screen,
    pairs_gray, shadow_gray, shadow_weight, treat_gray, duotone)


class PairScreenTests(unittest.TestCase):
    def test_screen_is_permutation_with_exact_nested_coverage(self):
        values = [rank for row in pair_screen() for rank in row]
        self.assertEqual(sorted(values), list(range(256)))
        previous = set()
        for threshold in range(257):
            occupied = {i for i, rank in enumerate(values) if rank < threshold}
            self.assertEqual(len(occupied), threshold)
            self.assertTrue(previous <= occupied)
            previous = occupied

    def test_only_four_cells_exchange_positions(self):
        ranks = pair_screen()
        changed_cells, changed_pixels = set(), 0
        for y in range(16):
            for x in range(16):
                if ranks[y][x] // 16 != BAYER_4[y % 4][x % 4]:
                    changed_cells.add((x // 4, y // 4))
                    changed_pixels += 1
        self.assertEqual(len(changed_cells), 4)
        self.assertEqual(changed_pixels, 8)

    def test_early_marks_form_horizontal_and_vertical_pairs(self):
        ranks = pair_screen()
        active = {(x, y) for y in range(16) for x in range(16) if ranks[y][x] < 32}
        horizontal = sum(((x + 1) % 16, y) in active for x, y in active)
        vertical = sum((x, (y + 1) % 16) in active for x, y in active)
        self.assertEqual(horizontal, 2)
        self.assertEqual(vertical, 2)

    def test_exact_reference_outside_signature_tonal_band(self):
        for value in (0, 4, 8, 62, 100, 148, 200, 255):
            image = Image.new("L", (32, 32), value)
            self.assertEqual(pairs_gray(image).tobytes(), shadow_gray(image).tobytes())
        image = Image.new("L", (32, 32), 30)
        self.assertNotEqual(pairs_gray(image).tobytes(), shadow_gray(image).tobytes())

    def test_uniform_tones_have_bounded_mean_error(self):
        for value in range(256):
            image = Image.new("L", (16, 16), value)
            result = pairs_gray(image)
            self.assertLess(abs(ImageStat.Stat(result).mean[0] - value), 2)

    def test_coordinate_stability_for_non_tile_aligned_crops(self):
        source = Image.frombytes("L", (67, 49), bytes((i * 17) % 256 for i in range(67 * 49)))
        bounds = (3, 7, 38, 32)
        full = pair_quantized(source).crop(bounds)
        crop = pair_quantized(source.crop(bounds), origin=(3, 7))
        self.assertEqual(full.tobytes(), crop.tobytes())
        for width in (1, 7, 15):
            image = Image.new("L", (width, 3), 30)
            self.assertEqual(pair_quantized(image).size, image.size)

    def test_deterministic_and_does_not_modify_input(self):
        image = Image.frombytes("L", (256, 16), bytes(range(256)) * 16)
        original = image.tobytes()
        self.assertEqual(pairs_gray(image).tobytes(), pairs_gray(image).tobytes())
        self.assertEqual(image.tobytes(), original)


class TreatmentTests(unittest.TestCase):
    def test_black_and_lights_remain_continuous(self):
        for value in (0, 4, 6, 148, 170, 220, 255):
            image = Image.new("L", (32, 32), value)
            self.assertEqual(image.tobytes(), shadow_gray(image).tobytes())

    def test_detail_protection_keeps_shadow_texture(self):
        image = Image.new("L", (32, 32), 30)
        image.paste(80, (16, 0, 32, 32))
        self.assertGreaterEqual(shadow_weight(image).getextrema()[0], 210)

    def test_pipeline_preserves_aspect_ratio_without_upscaling(self):
        image = Image.new("RGB", (200, 100), "gray")
        self.assertEqual(treat_gray(image, width=80).size, (80, 40))
        self.assertEqual(treat_gray(image, width=400).size, image.size)
        with self.assertRaises(ValueError):
            treat_gray(image, width=0)

    def test_transparency_composites_on_black_and_color_endpoints_match(self):
        gray = treat_gray(Image.new("RGBA", (8, 8), (255, 255, 255, 0)))
        self.assertEqual(gray.getextrema(), (0, 0))
        ramp = Image.frombytes("L", (256, 1), bytes(range(256)))
        color = duotone(ramp)
        self.assertEqual(color.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(color.getpixel((255, 0)), (242, 145, 145))

    def test_unchanging_frames_produce_identical_transport(self):
        frame = Image.frombytes("L", (256, 16), bytes(range(256)) * 16)
        original = frame.tobytes()
        self.assertEqual(treat_gray(frame).tobytes(), treat_gray(frame).tobytes())
        self.assertEqual(original, frame.tobytes())
