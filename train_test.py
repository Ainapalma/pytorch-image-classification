import torch                                            
import torchvision
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision.transforms as tt

from torchvision.datasets.utils import download_url
from torch.utils.data.dataloader import DataLoader
from torchvision.datasets import ImageFolder
from torchvision.utils import make_grid
from torch.utils.data import random_split
from torchsummary import summary

import matplotlib
import matplotlib.pyplot as plt
import multiprocessing
import os, tarfile, time

# Download the dataset
dataset_url = "https://s3.amazonaws.com/fast-ai-imageclas/imagewoof-160.tgz"
download_url(dataset_url, '.')

# Extract the archive
with tarfile.open('./imagewoof-160.tgz', 'r:gz') as tar: 
  tar.extractall(path = './data')

# Set the data directory paths
data_dir = './data/imagewoof-160'
train_directory = './data/imagewoof-160/train'
test_directory = './data/imagewoof-160/val'

# Set the model save path
path = 'imagewoof.pth'

# Number of workers
num_cpu = multiprocessing.cpu_count()

# Set generator
random_seed = 42
torch.manual_seed(random_seed)

# Create class names
class_names = ['Australian terrier', 
           'Border terrier', 
           'Samoyed', 
           'Beagle', 
           'Shih-Tzu', 
           'English foxhound', 
           'Rhodesian ridgeback', 
           'Dingo', 
           'Golden retriever', 
           'Old English sheepdog']

# Transform all the images into tensors
image_size_test = ImageFolder(train_directory, tt.ToTensor())

# Applying transforms to the data including resizing to 160x160
means = [0.4876, 0.4571, 0.3953]
stds = [0.2209, 0.2151, 0.2169]

image_transforms = {
    'train': tt.Compose([tt.RandomCrop(160, padding=1, padding_mode='reflect'), 
                         tt.RandomHorizontalFlip(),
                         tt.RandomRotation(degrees=15),
                         tt.ToTensor(),
                         tt.Normalize(mean = means, std = stds)]),
    'test': tt.Compose([tt.RandomResizedCrop(160),
                        tt.ToTensor(), tt.Normalize(mean = means, std = stds)])
}

# Load data from folders
dataset = {
    'train_full': ImageFolder(root=data_dir + '/train', transform=image_transforms['train']),
    'test': ImageFolder(root=data_dir + '/val', transform=image_transforms['test'])
}

# Split the dataset to training and validation
val_size = 0.95

n_train_examples = int(len(dataset['train_full']) * val_size)
n_valid_examples = len(dataset['train_full']) - n_train_examples

train_set, val_set = random_split(dataset['train_full'], 
                                           [n_train_examples, n_valid_examples])

print(f"Number of training examples: {len(train_set)}")
print(f"Number of validation examples: {len(val_set)}")

# Loading the data by batches
batch_size = 64

train_loaded = DataLoader(train_set, batch_size, 
                      shuffle = True, num_workers=num_cpu, pin_memory=True)
val_loaded = DataLoader(val_set, batch_size, 
                    num_workers=num_cpu, pin_memory=True)

# Accuracy function
def accuracy(outputs, labels):
    _, preds = torch.max(outputs, dim=1)
    return torch.tensor(torch.sum(preds == labels).item() / len(preds))

# Base class
class ImageClassificationBase(nn.Module):
    def training_step(self, batch):
        images, labels = batch 
        out = self(images)                  # Generate predictions
        loss = F.cross_entropy(out, labels) # Calculate loss
        return loss
    
    def validation_step(self, batch):
        images, labels = batch 
        out = self(images)                    # Generate predictions
        loss = F.cross_entropy(out, labels)   # Calculate loss
        acc = accuracy(out, labels)           # Calculate accuracy
        return {'val_loss': loss.detach(), 'val_acc': acc}
        
    def validation_epoch_end(self, outputs):
        batch_losses = [x['val_loss'] for x in outputs]
        epoch_loss = torch.stack(batch_losses).mean()   # Combine losses
        batch_accs = [x['val_acc'] for x in outputs]
        epoch_acc = torch.stack(batch_accs).mean()      # Combine accuracies
        return {'val_loss': epoch_loss.item(), 'val_acc': epoch_acc.item()}
    
    def epoch_end(self, epoch, result):
        print("Epoch [{}], train_loss: {:.4f}, val_loss: {:.4f}, val_acc: {:.4f}".format(
            epoch+1, result['train_loss'], result['val_loss'], result['val_acc']))

# Defining a model
class Imagewoof(ImageClassificationBase):
    def __init__(self):
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv2d(3, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(4, 4),

            nn.Conv2d(128, 256, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.Conv2d(256, 512, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(512, 512, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.Conv2d(512, 1024, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(4, 4),

            nn.Flatten(), 
            nn.Linear(1024 * 5 * 5, 1024),
            nn.ReLU(),
            nn.Linear(1024, 512),
            nn.Tanh(),
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, 10))
        
    def forward(self, xb):
        return self.network(xb)

model = Imagewoof()

# Move tensor to chosen device  
def to_device(data, device):
    if isinstance(data, (list,tuple)):
        return [to_device(x, device) for x in data]
    return data.to(device, non_blocking=True)

# Move data to a device
class DeviceDataLoader():
    def __init__(self, dl, device):
        self.dl = dl
        self.device = device
        
    def __iter__(self):
        for b in self.dl: 
            yield to_device(b, self.device)

    def __len__(self):
        return len(self.dl)

# Picking GPU if available, else CPU
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

# Transferring batches of data and moving model to the GPU if available
train_dl = DeviceDataLoader(train_loaded, device)
val_dl = DeviceDataLoader(val_loaded, device)
to_device(model, device)

# Checking summary
summary(model, (3, 160, 160), batch_size=batch_size)

@torch.no_grad()
# Evaluate performance on the validation set
def evaluate(model, val_loader):
    model.eval()
    outputs = [model.validation_step(batch) for batch in val_loader]
    return model.validation_epoch_end(outputs)

# Fit and evaluate to train the model using gradient descent
def fit(epochs, lr, model, train_loader, val_loader, opt_func=torch.optim.SGD):
    history = []
    optimizer = opt_func(model.parameters(), lr)
    for epoch in range(epochs):
        # Training Phase 
        model.train()
        train_losses = []
        for batch in train_loader:
            loss = model.training_step(batch)
            train_losses.append(loss)
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()
        # Validation phase
        result = evaluate(model, val_loader)
        result['train_loss'] = torch.stack(train_losses).mean().item()
        model.epoch_end(epoch, result)
        history.append(result)
    return history

# Evaluating the model the initial set of parameters
model = to_device(Imagewoof(), device)
evaluate(model, val_dl)

# Fitting model
num_epochs = 15
opt_func = torch.optim.Adam
lr = 0.0001

fit(num_epochs, lr, model, train_dl, val_dl, opt_func)

# Testing model on hidden set
test_loader = DeviceDataLoader(DataLoader(dataset['test'], batch_size), device)
result = evaluate(model, test_loader)
print(f"Final results: {result}")

# Save the entire model
print("\nSaving the model...")
torch.save(model, path)
