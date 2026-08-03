"""
research/ml_framework/models/logistic.py

Pure-Python implementation of Logistic Regression.
Uses mini-batch gradient descent with L2 regularization.
"""

import math
import random
from typing import List

class LogisticRegression:
    def __init__(self, learning_rate=0.01, epochs=100, batch_size=256, l2_penalty=0.01):
        self.lr = learning_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.l2 = l2_penalty
        self.weights = []
        self.bias = 0.0

    def _sigmoid(self, z: float) -> float:
        if z > 20: return 1.0
        if z < -20: return 0.0
        return 1.0 / (1.0 + math.exp(-z))

    def _dot(self, x: List[float]) -> float:
        return sum(w * f for w, f in zip(self.weights, x)) + self.bias

    def fit(self, X: List[List[float]], y: List[int]):
        """
        X: List of feature vectors
        y: List of 1s and 0s
        """
        if not X: return
        n_features = len(X[0])
        self.weights = [random.uniform(-0.01, 0.01) for _ in range(n_features)]
        self.bias = 0.0
        
        n_samples = len(X)
        indices = list(range(n_samples))
        
        # Cache to local variables to avoid slow attribute lookup inside loop
        weights = self.weights
        bias = self.bias
        lr = self.lr
        l2 = self.l2
        batch_size = self.batch_size
        epochs = self.epochs
        
        for epoch in range(epochs):
            random.shuffle(indices)
            
            for i in range(0, n_samples, batch_size):
                batch_idx = indices[i:i + batch_size]
                m = len(batch_idx)
                
                dw = [0.0] * n_features
                db = 0.0
                
                for idx in batch_idx:
                    x_i = X[idx]
                    
                    # Inline dot product (faster than sum + zip + dot)
                    z = 0.0
                    for j in range(n_features):
                        z += weights[j] * x_i[j]
                    z += bias
                    
                    # Inline sigmoid
                    if z > 20.0:
                        pred = 1.0
                    elif z < -20.0:
                        pred = 0.0
                    else:
                        pred = 1.0 / (1.0 + math.exp(-z))
                        
                    error = pred - y[idx]
                    
                    for j in range(n_features):
                        dw[j] += error * x_i[j]
                    db += error
                    
                for j in range(n_features):
                    weights[j] -= lr * ((dw[j] / m) + (l2 * weights[j]))
                bias -= lr * (db / m)
                
            lr *= 0.99
            
        self.weights = weights
        self.bias = bias
        self.lr = lr
            
    def predict_proba(self, X: List[List[float]]) -> List[float]:
        return [self._sigmoid(self._dot(x)) for x in X]
