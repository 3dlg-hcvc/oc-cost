import numpy as np
from .optimization import OCOpt
from .Annotations import BBox, predBBox, Annotations
import pulp
from scipy.spatial import Delaunay


class OC_Cost3D:
    def __init__(self, lm=1, iou_mode=False, giou_bb_mode=False, giou_ch_mode=False):
        self.lm = lm
        if iou_mode:
            self.mode = "iou"
        elif giou_bb_mode:
            self.mode = "giou_bb"
        elif giou_ch_mode:
            self.mode = "giou_ch"

    def getIntersectUnion(self, gt_mask, pred_mask):
        gt_mask_count = np.count_nonzero(gt_mask["mask"] == 1)
        pred_mask_count = np.count_nonzero(pred_mask["mask"] == 1)

        intersection = np.count_nonzero(np.logical_and(gt_mask["mask"] == 1, pred_mask["mask"] == 1))
        union = gt_mask_count + pred_mask_count - intersection

        return intersection, union

    def getIOU(self, gt_mask, pred_mask):

        intersect, union = self.getIntersectUnion(gt_mask, pred_mask)

        iou = intersect / (union)
        return iou

    def getGIOU(self, gt_mask, pred_mask):
        if self.mode == "giou_bb":
            union_mask = gt_mask["mask"] | pred_mask["mask"]
            min_xyz, max_xyz = np.min(gt_mask["xyz"][gt_mask["mask"]], axis=0), np.max(gt_mask["xyz"][gt_mask["mask"]], axis=0)
            c_mask = [int(np.all((min_xyz <= point) & (point <= max_xyz), axis=0)) for point in gt_mask["xyz"]]

            iou = self.getIOU(gt_mask, pred_mask)

            Giou = iou - np.count_nonzero(c_mask & ~union_mask) / np.count_nonzero(c_mask)
            return Giou
        else:
            union_mask = gt_mask["mask"] | pred_mask["mask"]
            union_xyz = gt_mask["xyz"][union_mask]
            triangulation = Delaunay(union_xyz)
            c_mask = triangulation.find_simplex(gt_mask["xyz"]) >= 0
            iou = self.getIOU(gt_mask, pred_mask)

            Giou = iou - np.count_nonzero(c_mask & ~union_mask) / np.count_nonzero(c_mask)
            return Giou


    def getCloc(self, gt_mask, pred_mask):
        cost: float = 0
        if self.mode == "iou":
            cost = (1 - self.getIOU(gt_mask, pred_mask)) / 2
        else:
            cost = (1 - self.getGIOU(gt_mask, pred_mask)) / 2
        
        return cost

    def getCcls(self, gt_mask, pred_mask):
        clt = gt_mask["label"]
        clp = pred_mask["label"]

        preci = pred_mask["conf"]
        ccls = 0.5
        if clt == clp:
            ccls = (1 - preci) / 2
        else:
            ccls = (1 + preci) / 2
        return ccls

    def getoneCost(self, gt_mask, pred_mask):
        Cloc = self.getCloc(gt_mask, pred_mask)
        CCls = self.getCcls(gt_mask, pred_mask)

        return (self.lm * Cloc) + ((1 - self.lm) * CCls)

    def build_C_matrix(self, gt, preds):
        n = len(gt["masks"])
        m = len(preds["masks"])

        self.cost = np.zeros((m, n))

        for i in range(m):
            for j in range(n):
                gt_mask = {"mask": gt["masks"][j], "label": gt["gt_labels"][j], "xyz": gt["xyz"]}
                pred_mask = {"mask": preds["masks"][i], "label": preds["pred_labels"][i], "conf": preds["conf"][i]}
                self.cost[i][j] = self.getoneCost(gt_mask, pred_mask)
        return self.cost

    def optim(self, beta):
        m = self.cost.shape[0] + 1
        n = self.cost.shape[1] + 1
        opt = OCOpt(m, n, beta)
        opt.set_cost_matrix(self.cost)
        opt.setVariable()
        opt.setObjective()
        opt.setConstrain()

        result = opt.prob.solve(pulp.PULP_CBC_CMD(
            msg=0, timeLimit=100))
        p_matrix = np.zeros((m, n))

        # print('objective value: {}'.format(pulp.value(opt.prob.objective)))
        # print('solution')
        for i in range(opt.m):
            for j in range(opt.n):
                #print(f'{opt.variable[j][i]} = {pulp.value(opt.variable[j][i])}')
                p_matrix[j][i] = pulp.value(opt.variable[j][i])
        p_matrix[-1][-1] = 0
        p_tilde_matrix = p_matrix / np.sum(p_matrix)
        self.p_matrix = p_matrix
        self.p_tilde_matrix = p_tilde_matrix
        self.opt = opt
        return p_tilde_matrix
