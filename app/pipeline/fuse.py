"""Camera helper shared by the panorama and layout stages."""
import numpy as np
def cam_matrices(room, P, i):
    """Room-frame camera basis (rows: right, up, forward), centre, and intrinsics at reconstruction resolution."""
    cb = room["cam_basis"][i]; R = np.array([cb["right"], cb["up"], cb["fwd"]], float); c = np.array(cb["pos"], float)
    K = P["intrinsic"][i].astype(float); return R, c, K
