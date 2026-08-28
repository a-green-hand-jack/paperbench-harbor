# Research Overview

## Problem

This smoke sample studies whether a compact feature representation can classify synthetic documents into two categories.

## Method

We create 1,000 deterministic synthetic documents, extract a 16-dimensional feature vector, and train a logistic-regression classifier. We use an 80/20 train/test split and report accuracy on the held-out test set.

## Results

The classifier achieves 0.90 test accuracy. The result is illustrative benchmark material for validating the Harbor task contract; it is not a claim about a real-world dataset.

## Required emphasis

The paper should clearly separate the synthetic setup, the feature representation, the training procedure, and the held-out evaluation.
