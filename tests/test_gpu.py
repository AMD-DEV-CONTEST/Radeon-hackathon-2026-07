import torch


def check_gpu():
    assert torch.cuda.is_available()
    print(torch.cuda.get_device_name())


if __name__ == "__main__":
    check_gpu()
