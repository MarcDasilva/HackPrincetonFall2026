# earrecon

One ear photo → 3D ear mesh (`ear.obj` / `ear.ply` / `ear.glb`, in mm) with the pretrained
[AudioEar](https://github.com/seanywang0408/AudioEar) networks (Huang et al., AAAI 2023), plus SAM 2 to cut
the ear out from a box. Runs on CUDA, Apple MPS or CPU, without PyTorch3D.

AudioEar's code and ear model come from the `third_party/AudioEar` submodule; weights come from
`scripts/fetch_weights.sh`. From `backend/`:

```bash
.venv/bin/python -m earrecon.reconstruct ear.jpg --box x0,y0,x1,y1 --height-mm 62 --out data/cli/ear
.venv/bin/python -m earrecon.reconstruct ear.jpg --box x0,y0,x1,y1 --left      # photo of a left ear
```

The box is in the photo's full-resolution pixels. Outputs: the mesh files plus `mask.png`, `input.jpg`
and `overlay.jpg` to check the cut-out and the fit.

## Limits

- The released encoder barely personalises shape: across 29 AudioEar3D subjects, predictions differ from
  the average by a median of 0.3 mm. Treat the mesh as a well-fitted template ear.
- One photo cannot give real size; `--height-mm` scales it (measure the ear, top to lobe).
- Only the visible ear is modelled; the ear canal is not.
