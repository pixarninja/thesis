# Taken from: https://github.com/aitorzip/PyTorch-SRGAN
# python train.py --blockDim 32 --cuda

import argparse
import os as os
import sys as sys
import numpy as np
import cv2 as cv2

import torch
import torch.optim as optim
import torch.optim.lr_scheduler as lr_scheduler
import torch.nn as nn
from torch.autograd import Variable

import torchvision
import torchvision.datasets as datasets
import torchvision.transforms as transforms
import torchvision.utils as vutils

from tensorboard_logger import configure, log_value

from models import Generator, Discriminator, FeatureExtractor

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--blockDim', type=int, default=64, help='size of block to use')
    parser.add_argument('--generation', type=int, default=100, help='epochs to wait between writing images')
    parser.add_argument('--workers', type=int, default=2, help='number of data loading workers')
    parser.add_argument('--batchSize', type=int, default=16, help='input batch size')
    parser.add_argument('--upSampling', type=int, default=1, help='low to high resolution scaling factor')
    parser.add_argument('--nEpochs', type=int, default=100, help='number of epochs to train for')
    parser.add_argument('--generatorLR', type=float, default=0.0001, help='learning rate for generator')
    parser.add_argument('--discriminatorLR', type=float, default=0.0001, help='learning rate for discriminator')
    parser.add_argument('--cuda', action='store_true', help='enables cuda')
    parser.add_argument('--nGPU', type=int, default=1, help='number of GPUs to use')
    parser.add_argument('--generatorWeights', type=str, default='', help="path to generator weights (to continue training)")
    parser.add_argument('--discriminatorWeights', type=str, default='', help="path to discriminator weights (to continue training)")
    parser.add_argument('--out', type=str, default='checkpoints', help='folder to output model checkpoints')
    parser.add_argument('--outf', type=str, default='output', help='folder to output images')

    opt = parser.parse_args()
    print(opt)

    try:
        os.makedirs(opt.out)
    except OSError:
        pass

    if torch.cuda.is_available() and not opt.cuda:
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")

    transform = transforms.Compose([transforms.RandomCrop(opt.blockDim),
                                    transforms.ToTensor()])

    normalize = transforms.Normalize(mean = [0.485, 0.456, 0.406],
                                    std = [0.229, 0.224, 0.225])

    # Replace loader with hardcoded values.
    data_prefix = 'C:/Users/wesha/Git/dynamic_frame_generator/python/training/' + str(opt.blockDim) + '/'
    dataset = datasets.ImageFolder(root=data_prefix + 'validation/', transform=transform)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=opt.batchSize,
                                             shuffle=True, num_workers=int(opt.workers))

    generator = Generator(16, opt.upSampling)
    if opt.generatorWeights != '':
        generator.load_state_dict(torch.load(opt.generatorWeights))
    print(generator)

    discriminator = Discriminator()
    if opt.discriminatorWeights != '':
        discriminator.load_state_dict(torch.load(opt.discriminatorWeights))
    print(discriminator)

    # For the content loss
    feature_extractor = FeatureExtractor(torchvision.models.vgg19(pretrained=True))
    print(feature_extractor)
    content_criterion = nn.MSELoss()
    adversarial_criterion = nn.BCELoss()

    ones_const = Variable(torch.ones(opt.batchSize, 1))

    # if gpu is to be used
    if opt.cuda:
        generator.cuda()
        discriminator.cuda()
        feature_extractor.cuda()
        content_criterion.cuda()
        adversarial_criterion.cuda()
        ones_const = ones_const.cuda()

    optim_generator = optim.Adam(generator.parameters(), lr=opt.generatorLR)
    optim_discriminator = optim.Adam(discriminator.parameters(), lr=opt.discriminatorLR)

    configure('logs/' + '-' + str(opt.batchSize) + '-' + str(opt.generatorLR) + '-' + str(opt.discriminatorLR), flush_secs=5)

    low_res = torch.FloatTensor(opt.batchSize, 3, opt.blockDim, opt.blockDim)

    # Pre-train generator using raw MSE loss
    print('Generator pre-training')
    for epoch in range(2):
        mean_generator_content_loss = 0.0

        for i, data in enumerate(dataloader, 0):
            # Generate data
            high_res_real = data[0]
            print('... ' + str(np.shape(high_res_real)))
            if np.shape(high_res_real)[0] != opt.batchSize:
                continue

            # Downsample images to low resolution
            for j in range(opt.batchSize):
                img = high_res_real[j].numpy().transpose(1, 2, 0)
                
                # Add noise.
                img_noise = np.random.normal(loc=0, scale=1, size=img.shape).astype('float32')
                img = cv2.addWeighted(img, 0.9, img_noise, 0.1, 0)

                # Gaussian blur.
                img = cv2.GaussianBlur(img, (7, 7), 0)

                low_res[j] = torch.from_numpy(np.asarray(img).transpose(2, 0, 1))
                high_res_real[j] = normalize(high_res_real[j])

            # Generate real and fake inputs
            if opt.cuda:
                high_res_real = Variable(high_res_real.cuda())
                high_res_fake = generator(Variable(low_res).cuda())
            else:
                high_res_real = Variable(high_res_real)
                high_res_fake = generator(Variable(low_res))

            ######### Train generator #########
            generator.zero_grad()

            generator_content_loss = content_criterion(high_res_fake, high_res_real)
            mean_generator_content_loss += generator_content_loss.data

            generator_content_loss.backward()
            optim_generator.step()

            ######### Status and display #########
            sys.stdout.write('\r[%d/%d][%d/%d] Generator_MSE_Loss: %.4f' % (epoch + 1, 2, i, len(dataloader), generator_content_loss.data))
            if i % opt.generation == 0:
                vutils.save_image(low_res,
                        '%s/low_res.png' % opt.outf,
                        normalize=True)
                vutils.save_image(high_res_real,
                        '%s/high_res_real.png' % opt.outf,
                        normalize=True)
                vutils.save_image(high_res_fake,
                        '%s/high_res_fake.png' % opt.outf,
                        normalize=True)

        sys.stdout.write('\r[%d/%d][%d/%d] Generator_MSE_Loss: %.4f\n' % (epoch + 1, 2, i, len(dataloader), mean_generator_content_loss/len(dataloader)))
        log_value('generator_mse_loss', mean_generator_content_loss/len(dataloader), epoch)

    # Do checkpointing
    torch.save(generator.state_dict(), '%s/generator_pretrain.pth' % opt.out)

    # SRGAN training
    optim_generator = optim.Adam(generator.parameters(), lr=opt.generatorLR*0.1)
    optim_discriminator = optim.Adam(discriminator.parameters(), lr=opt.discriminatorLR*0.1)

    print('SRGAN training')
    for epoch in range(opt.nEpochs):
        mean_generator_content_loss = 0.0
        mean_generator_adversarial_loss = 0.0
        mean_generator_total_loss = 0.0
        mean_discriminator_loss = 0.0

        for i, data in enumerate(dataloader):
            # Generate data
            high_res_real, _ = data
            print('... ' + str(np.shape(high_res_real)))
            if np.shape(high_res_real)[0] != opt.batchSize:
                continue

            # Downsample images to low resolution
            for j in range(opt.batchSize):
                img = high_res_real[j].numpy().transpose(1, 2, 0)
                
                # Add noise.
                img_noise = np.random.normal(loc=0, scale=1, size=img.shape).astype('float32')
                img = cv2.addWeighted(img, 0.9, img_noise, 0.1, 0)

                # Gaussian blur.
                img = cv2.GaussianBlur(img, (7, 7), 0)

                low_res[j] = torch.from_numpy(np.asarray(img).transpose(2, 0, 1))
                high_res_real[j] = normalize(high_res_real[j])

            # Generate real and fake inputs
            if opt.cuda:
                high_res_real = Variable(high_res_real.cuda())
                high_res_fake = generator(Variable(low_res).cuda())
                target_real = Variable(torch.rand(opt.batchSize,1)*0.5 + 0.7).cuda()
                target_fake = Variable(torch.rand(opt.batchSize,1)*0.3).cuda()
            else:
                high_res_real = Variable(high_res_real)
                high_res_fake = generator(Variable(low_res))
                target_real = Variable(torch.rand(opt.batchSize,1)*0.5 + 0.7)
                target_fake = Variable(torch.rand(opt.batchSize,1)*0.3)
            
            ######### Train discriminator #########
            discriminator.zero_grad()

            discriminator_loss = adversarial_criterion(discriminator(high_res_real), target_real) + \
                                 adversarial_criterion(discriminator(Variable(high_res_fake.data)), target_fake)
            mean_discriminator_loss += discriminator_loss.data
            
            discriminator_loss.backward()
            optim_discriminator.step()

            ######### Train generator #########
            generator.zero_grad()

            real_features = Variable(feature_extractor(high_res_real).data)
            fake_features = feature_extractor(high_res_fake)

            generator_content_loss = content_criterion(high_res_fake, high_res_real) + 0.006*content_criterion(fake_features, real_features)
            mean_generator_content_loss += generator_content_loss.data
            generator_adversarial_loss = adversarial_criterion(discriminator(high_res_fake), ones_const)
            mean_generator_adversarial_loss += generator_adversarial_loss.data

            generator_total_loss = generator_content_loss + 1e-3*generator_adversarial_loss
            mean_generator_total_loss += generator_total_loss.data
            
            generator_total_loss.backward()
            optim_generator.step()   
            
            ######### Status and display #########
            sys.stdout.write('\r[%d/%d][%d/%d] Discriminator_Loss: %.4f Generator_Loss (Content/Advers/Total): %.4f/%.4f/%.4f' % (epoch + 1, opt.nEpochs, i, len(dataloader),
            discriminator_loss.data, generator_content_loss.data, generator_adversarial_loss.data, generator_total_loss.data))
            if i % opt.generation == 0:
                vutils.save_image(low_res,
                        '%s/low_res.png' % opt.outf,
                        normalize=True)
                vutils.save_image(high_res_real,
                        '%s/high_res_real.png' % opt.outf,
                        normalize=True)
                vutils.save_image(high_res_fake,
                        '%s/high_res_fake.png' % opt.outf,
                        normalize=True)

        sys.stdout.write('\r[%d/%d][%d/%d] Discriminator_Loss: %.4f Generator_Loss (Content/Advers/Total): %.4f/%.4f/%.4f\n' % (epoch + 1, opt.nEpochs, i, len(dataloader),
        mean_discriminator_loss/len(dataloader), mean_generator_content_loss/len(dataloader), 
        mean_generator_adversarial_loss/len(dataloader), mean_generator_total_loss/len(dataloader)))

        log_value('generator_content_loss', mean_generator_content_loss/len(dataloader), epoch)
        log_value('generator_adversarial_loss', mean_generator_adversarial_loss/len(dataloader), epoch)
        log_value('generator_total_loss', mean_generator_total_loss/len(dataloader), epoch)
        log_value('discriminator_loss', mean_discriminator_loss/len(dataloader), epoch)

        # Do checkpointing
        torch.save(generator.state_dict(), '%s/generator_final.pth' % opt.out)
        torch.save(discriminator.state_dict(), '%s/discriminator_final.pth' % opt.out)
