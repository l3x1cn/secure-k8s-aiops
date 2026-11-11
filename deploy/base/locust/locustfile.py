"""Stały ruch do frontendu (T18), na którym uczy się detektor (T20, T23).

Liczba użytkowników to sinusoida 10 ± 8 o okresie 30 min z szumem. Każdy użytkownik
w 70% iteracji pobiera katalog (`GET /`), w 30% składa zamówienie (`POST /order`).
Plik trafia do ConfigMap przez configMapGenerator (deploy/base/locust/kustomization.yaml).
"""

import math
import random

from locust import HttpUser, LoadTestShape, between, task

# Katalog frontendu (PRODUCTS w services/frontend/src/frontend/app.py): zmieniaj razem.
PRODUCTS = ["kubek", "koszulka", "naklejki", "bluza", "czapka"]

MEAN_USERS = 10
AMPLITUDE_USERS = 8
PERIOD_SECONDS = 30 * 60
# Szum losowany raz na minutę: częstsza zmiana liczby użytkowników tylko by ich zatrzymywała i startowała.
NOISE_SIGMA_USERS = 1.5
NOISE_INTERVAL_SECONDS = 60
SPAWN_RATE = 2


class Shopper(HttpUser):
    wait_time = between(1, 3)

    @task(7)
    def browse(self) -> None:
        self.client.get("/")

    @task(3)
    def order(self) -> None:
        self.client.post(
            "/order",
            json={
                "product_id": random.choice(PRODUCTS),
                "quantity": random.randint(1, 3),
            },
        )


class SineWithNoise(LoadTestShape):
    """Bez końca: tick() nigdy nie zwraca None, więc Locust nie kończy testu."""

    def __init__(self) -> None:
        super().__init__()
        self._noise_slot = -1
        self._noise = 0.0

    def tick(self) -> tuple[int, float]:
        run_time = self.get_run_time()
        slot = int(run_time // NOISE_INTERVAL_SECONDS)
        if slot != self._noise_slot:
            self._noise_slot = slot
            self._noise = random.gauss(0.0, NOISE_SIGMA_USERS)
        phase = 2 * math.pi * run_time / PERIOD_SECONDS
        users = MEAN_USERS + AMPLITUDE_USERS * math.sin(phase) + self._noise
        # Szum nie wyprowadza poza zakres 10 ± 8 z issue.
        low, high = MEAN_USERS - AMPLITUDE_USERS, MEAN_USERS + AMPLITUDE_USERS
        return round(min(max(users, low), high)), SPAWN_RATE
