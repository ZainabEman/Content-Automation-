# Rejected sample (PRD v6 §2, R3.1, R3.6)

Every image the system generated before v6 is rejected. `outputs/` is git-ignored, so this is a
small downscaled sample (360 px wide JPEGs) that together covers every recurring failure pattern.
Each `<name>.json` names its source in `outputs/`, what the image was meant to be (`category`,
`roman`, `provider`, `lastSlide`, the app's `logoBox`, `website`), the text visible in the image
(`read`, transcribed by eye: what the OCR or vision check returns) and the intended copy. `expect`
lists the reason codes the design checks must report (workflows/image_check.py); the image may
fail for more reasons.

| Pattern (R3.1 and found in outputs/)                                   | Fixtures       | Code(s)                       |
|------------------------------------------------------------------------|----------------|-------------------------------|
| 1 layout coordinates printed in the image ("x 66-94%", "y 47-60%")     | 01, 02         | coordinates                   |
| 2 garbled fake text ("v-inmleie") and a doubled/extra wordmark         | 02, 09         | stray_text, extra_logo        |
| 3 a flat bright royal-blue fill as the base                            | 01, 02, 05, 06, 09 | flat_blue                 |
| 4 large empty panels, tiny icons, CTA pill colliding with its arrow    | 02, 03, 05     | stray_text, flat_blue (the CTA gap is checked on the render manifest) |
| 5 a real photo of Roman as the final image with a flat blue block      | 07             | real_photo, roman_logo        |
| 6 the logo overlapped by other elements                                | 01, 02         | logo_overlap                  |
| found: the style guide's type specimen copied into the image           | 03             | placeholder                   |
| found: a light grey or white base (old "Light Sweep" variants)         | 04, 10         | light_base                    |
| found: a slide number on a carousel slide                              | 05             | slide_number                  |
| found: an off-brand warm daylight stock photo                          | 08             | light_base                    |
| found: placeholder text, English copy, logo on a carousel cover        | 09, 10         | placeholder, not_german, carousel_logo, stray_text |
