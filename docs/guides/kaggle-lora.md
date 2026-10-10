# Train and test Roman's LoRA for free on Kaggle

Kaggle gives free GPU time: a T4 or P100 with 16 GB, about 30 hours a week (unverified, see
docs/PHASE2-DECISION.md). The two notebooks in `notebooks/` run on their own once started.

- `kaggle_train_lora.ipynb` trains a Z-Image Turbo LoRA.
- `kaggle_test_lora.ipynb` makes a likeness test sheet.

Nothing here costs money. Qwen-Image-2512 is too big for 16 GB, so only Z-Image is trained here.

Roman's consent says the photos and the model stay private. Keep the dataset, both notebooks
and their outputs **Private** on Kaggle, and never publish them.

## Steps

1. **On this PC**, run `uv run ca lora prepare`. It checks the consent and the photos and
   writes `outputs/lora/dataset_<date>.zip`.
2. **Kaggle account:** sign in and verify your phone number. Kaggle needs it before a notebook
   may use a GPU and the internet.
3. **Dataset:** Kaggle → Datasets → New Dataset. Upload the zip, give it a name (e.g.
   `roman-lora-dataset`), set **Private**, then Create. It is fine whether Kaggle unpacks the
   zip or not.
4. **Training notebook:** Kaggle → Code → New Notebook → File → Import Notebook, then upload
   `notebooks/kaggle_train_lora.ipynb`.
5. In the right panel: Add Input → Your Datasets → the dataset from step 3.
6. In the right panel, under Session options: Accelerator **GPU T4 x2**, Internet **On**.
7. Click **Save Version → Save & Run All (Commit) → Save**. It runs in the background, so you
   can close the browser. Training stops by itself after 9 hours at most. Every checkpoint
   finished by then is kept.
8. When the version shows as finished, open it → **Output**, and download
   `r0man_bg_z_image_turbo_outputs.zip`. It holds the checkpoints, the sample images, the log
   and `status.json`. `status.json` says "done", "stopped: time budget reached" or what failed.
9. **Pick a checkpoint:** in `samples/`, each image name contains its step (e.g.
   `__000001500_`). Choose the step where he looks most like Roman without looking stiff or
   over-sharpened. The checkpoint with the same step number is your pick.
10. **Test notebook:** import `notebooks/kaggle_test_lora.ipynb` the same way (step 4). Then:
    Add Input → Notebook Output → the training notebook. Or upload the chosen `.safetensors`
    as another private dataset.
11. In the test notebook's first code cell, set `LORA_FILE = "<the file name from step 9>"`.
    Leave it empty for the final file. Set GPU T4 x2 and Internet On as in step 6.
12. **Save & Run All** again (about 20–40 minutes, unverified). Download `lora_test.zip` from
    Output and open `contact_sheet.jpg`. It shows 6 scenes, each at strength 0.7, 0.9 and 1.0.
13. **Judge the likeness:** face, hairline, build and age against his photos. If no strength
    looks like him, test another checkpoint (steps 11–12). Or add more varied photos to
    `assets/reference/identity/person_01/extra/`, then repeat from step 1.
14. Note the winning file and the best strength. The strength goes into `loraStrength` in
    `config/comfyui.json` later.
15. **When RunPod has credit (Step 5):**
    1. Upload the chosen file to `models/loras/` on the network volume.
    2. Run `uv run ca lora set zimage <file>`.
    3. Run `uv run ca doctor`.
    4. Run the paid comparison only after the cost "ok".

## If something goes wrong

- **"No GPU":** the Accelerator is not set (step 6). Fix it and run again.
- **"No dataset …":** the dataset is not attached (step 5), or it has fewer than 9 photos.
- **Out of GPU memory:** if this happens before the first checkpoint, the notebook retries once
  at 512/768 px. `status.json` notes it.
- **"loss was 0/NaN for the first 30 steps":** the run stopped itself after a few minutes
  instead of wasting hours. Send `status.json` and `train_log.txt` to Codex.
- **Continue a run that hit the time limit:** in a new version, also add the earlier
  version's output (Add Input → Notebook Output). The notebook continues from its newest
  checkpoint that learned something.
- **"The LoRA does not fit this model":** the test notebook could not match the LoRA to the
  model. It prints example names; send them to Codex.
- **Weekly GPU hours used up:** wait for Kaggle's weekly reset. A training run takes up to
  about 10 hours of it.
