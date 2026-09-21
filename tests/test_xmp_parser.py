"""
Unit tests for the XMP Parser & Classifier (xmp_parser.py).
"""

import unittest
from xmp_parser import XmpParser, XmpCategory


SAMPLE_XMP = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:PresetType="Normal"
   crs:Cluster=""
   crs:UUID="ABCD1234EF56"
   crs:SupportsAmount="True"
   crs:ProcessVersion="15.4"
   crs:Exposure2012="+0.35"
   crs:Contrast2012="+15"
   crs:Highlights2012="-25"
   crs:Shadows2012="+20"
   crs:Whites2012="+10"
   crs:Blacks2012="-12"
   crs:Clarity2012="+14"
   crs:Texture="+8"
   crs:Dehaze="+5"
   crs:Vibrance="+18"
   crs:Saturation="-5"
   crs:PostCropVignetteAmount="-15"
   crs:GrainAmount="22"
   crs:GrainSize="25"
   crs:HueAdjustmentRed="-10"
   crs:HueAdjustmentGreen="+25"
   crs:SaturationAdjustmentOrange="-12"
   crs:LuminanceAdjustmentBlue="+15"
   crs:SomeUnknownProprietaryTag="ValueXYZ">
   <crs:ToneCurvePV2012>
    <rdf:Seq>
     <rdf:li>0, 0</rdf:li>
     <rdf:li>64, 55</rdf:li>
     <rdf:li>192, 205</rdf:li>
     <rdf:li>255, 255</rdf:li>
    </rdf:Seq>
   </crs:ToneCurvePV2012>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""


class TestXmpParser(unittest.TestCase):

    def test_parse_sample_xmp(self):
        res = XmpParser.parse_xmp_content(SAMPLE_XMP)

        # Tone parameters
        self.assertEqual(res["default_sliders"]["exposure"], 0.35)
        self.assertEqual(res["default_sliders"]["contrast"], 15.0)
        self.assertEqual(res["default_sliders"]["highlights"], -25.0)
        self.assertEqual(res["default_sliders"]["shadows"], 20.0)

        # Spatial parameters
        self.assertEqual(res["spatial"]["clarity"], 14.0)
        self.assertEqual(res["spatial"]["texture"], 8.0)
        self.assertEqual(res["spatial"]["dehaze"], 5.0)
        self.assertEqual(res["spatial"]["vignette"]["amount"], -15.0)
        self.assertEqual(res["spatial"]["grain"]["amount"], 22.0)

        # HSL
        self.assertEqual(res["hsl_hue"]["Red"], -10.0)
        self.assertEqual(res["hsl_hue"]["Green"], 25.0)
        self.assertEqual(res["hsl_sat"]["Orange"], -12.0)
        self.assertEqual(res["hsl_lum"]["Blue"], 15.0)

        # Tone curve
        self.assertEqual(len(res["tone_curves"]["master"]), 4)
        self.assertEqual(res["tone_curves"]["master"][1], (64.0, 55.0))

        # Unsupported tag detection
        self.assertIn("SomeUnknownProprietaryTag", res["unsupported_parameters"])
        self.assertTrue(res["calibration_recommended"])


if __name__ == "__main__":
    unittest.main()
