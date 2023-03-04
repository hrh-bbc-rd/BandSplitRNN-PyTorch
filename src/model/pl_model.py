import torch
import torch.nn as nn
import pytorch_lightning as pl
from torch.optim import Optimizer, lr_scheduler
from typing import Tuple, Dict
from omegaconf import DictConfig


class PLModel(pl.LightningModule):
    def __init__(
            self,
            model: nn.Module,
            featurizer: nn.Module,
            inverse_featurizer: nn.Module,
            augmentations: nn.Module,
            opt: Optimizer,
            sch: lr_scheduler._LRScheduler,
            hparams: DictConfig
    ):
        super().__init__()

        # augmentations
        self.augmentations = augmentations

        # featurizers
        self.featurizer = featurizer
        self.inverse_featurizer = inverse_featurizer

        # model
        self.model = model

        # losses
        self.mae_specR = nn.L1Loss()
        self.mae_specI = nn.L1Loss()
        self.mae_time = nn.L1Loss()

        # opts
        self.opt = opt
        self.sch = sch

        # logging
        self.save_hyperparameters(hparams)

        # other
        self.tracked_gradient_global_only()

    def training_step(
            self, batch, batch_idx
    ) -> torch.Tensor:
        """
        Input shape: [batch_size, n_sources, n_channels, time]
        Output: loss
        """
        loss, loss_dict = self.step(batch)

        # logging
        for k in loss_dict:
            self.log(f"train/{k}", loss_dict[k])
        self.log("train/loss", loss)

        return loss

    def validation_step(
            self, batch, batch_idx
    ) -> torch.Tensor:
        loss, loss_dict = self.step(batch)
        # logging
        for k in loss_dict:
            self.log(f"val/{k}", loss_dict[k])
        self.log("val/loss", loss, prog_bar=True)

        return loss

    def step(
            self, batch
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        """
        Input shape: [batch_size, n_sources, n_channels, time]
        """
        # augmentations
        batch = self.augmentations(batch)
        tgt_time = batch[:, 1]
        # STFT
        batch = self.featurizer(batch)
        mix_freq, tgt_freq = batch[:, 0], batch[:, 1]
        # apply model
        tgt_freq_hat = self.model(mix_freq)
        tgt_time_hat = self.inverse_featurizer(tgt_freq_hat, length=tgt_time.shape[-1])
        # compute loss
        loss, loss_dict = self.compute_losses(
            tgt_freq_hat, tgt_freq,
            tgt_time_hat, tgt_time
        )
        return loss, loss_dict

    def compute_losses(
            self,
            tgt_freq_hat: torch.Tensor,
            tgt_freq: torch.Tensor,
            tgt_time_hat: torch.Tensor,
            tgt_time: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        # frequency domain
        lossR = self.mae_specR(
            tgt_freq_hat.real, tgt_freq.real
        )
        lossI = self.mae_specI(
            tgt_freq_hat.imag, tgt_freq.imag
        )
        # time domain
        lossT = self.mae_time(
            tgt_time_hat, tgt_time
        )
        loss_dict = {
            "lossSpecR": lossR,
            "lossSpecI": lossI,
            "lossTime": lossT
        }
        loss = sum(loss_dict.values())
        return loss, loss_dict

    def configure_optimizers(self):
        return [self.opt], [self.sch]

    def get_progress_bar_dict(self):
        tqdm_dict = super().get_progress_bar_dict()
        tqdm_dict.pop("v_num", None)
        return tqdm_dict

    @staticmethod
    def tracked_gradient_global_only():
        def remove_per_weight_norms(func):
            def f(*args):
                norms = func(*args)

                norms = dict(filter(lambda elem: '_total' in elem[0], norms.items()))

                return norms

            return f
        pl.utilities.grad_norm = remove_per_weight_norms(pl.utilities.grad_norm)