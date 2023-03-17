import torch
import torch.nn as nn


class RNNModule(nn.Module):
    """
    RNN submodule of BandSequence module
    """
    def __init__(
            self,
            group_dim_size: int,
            input_dim_size: int,
            hidden_dim_size: int,
            rnn_type: str = 'lstm',
            bidirectional: bool = True
    ):
        super(RNNModule, self).__init__()
        self.groupnorm = nn.GroupNorm(1, group_dim_size)
        self.rnn = getattr(nn, rnn_type)(
            input_dim_size, hidden_dim_size, batch_first=True, bidirectional=bidirectional
        )
        self.fc = nn.Linear(
            hidden_dim_size * 2 if bidirectional else hidden_dim_size,
            input_dim_size
        )

    def forward(
            self,
            x: torch.Tensor
    ):
        """
        Input shape:
            across T - [batch_size, k_subbands, time, n_features]
            OR
            across K - [batch_size, time, k_subbands, n_features]
        """
        B, K, T, N = x.shape  # across T, across K - keep in mind T->K, K->T

        out = self.groupnorm(x)  # [B, K, T, N] across T,    [B, T, K, N] across K
        out = out.view(B * K, T, N)  # [BK, T, N] across T,      [BT, K, N] across K
        out, _ = self.rnn(out)  # [BK, T, H] across T,      [BT, K, H] across K
        out = self.fc(out)  # [BK, T, N] across T,      [BT, K, N] across K
        out = out.view(B, K, T, N) + x  # [B, K, T, N] across T,    [B, T, K, N] across K
        out = out.permute(0, 2, 1, 3).contiguous()  # [B, T, K, N] across T,    [B, K, T, N] across K
        return out


class BandSequenceModelModule(nn.Module):
    """
    BandSequence (2nd) Module of BandSplitRNN.
    Runs input through n BiLSTMs in two dimensions - time and subbands.
    """
    def __init__(
            self,
            k_subbands: int,
            t_timesteps: int,
            input_dim_size: int,
            hidden_dim_size: int,
            rnn_type: str = 'lstm',
            bidirectional: bool = True,
            num_layers: int = 12,
    ):
        super(BandSequenceModelModule, self).__init__()

        self.bsrnn = nn.ModuleList([])

        for _ in range(num_layers):
            rnn_across_t = RNNModule(
                k_subbands, input_dim_size, hidden_dim_size, rnn_type, bidirectional
            )
            rnn_across_k = RNNModule(
                t_timesteps, input_dim_size, hidden_dim_size, rnn_type, bidirectional
            )
            self.bsrnn.append(
                nn.Sequential(rnn_across_t, rnn_across_k)
            )

    def forward(self, x: torch.Tensor):
        """
        Input shape: [batch_size, k_subbands, time, n_features]
        Output shape: [batch_size, k_subbands, time, n_features]
        """
        for i in range(len(self.bsrnn)):
            x = self.bsrnn[i](x)
        return x


if __name__ == '__main__':
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    batch_size, k_subbands, t_timesteps, input_dim = 4, 41, 259, 128
    in_features = torch.rand(batch_size, k_subbands, t_timesteps, input_dim).to(device)

    cfg = {
        "k_subbands": k_subbands,
        "t_timesteps": t_timesteps,
        "input_dim_size": 128,
        "hidden_dim_size": 256,
        "rnn_type": "LSTM",
        "bidirectional": True,
        "num_layers": 12
    }
    model = BandSequenceModelModule(**cfg).to(device)
    _ = model.eval()

    with torch.no_grad():
        out_features = model(in_features)

    print(f"In: {in_features.shape}\nOut: {out_features.shape}")
    print(f"Total number of parameters: {sum([p.numel() for p in model.parameters()])}")
