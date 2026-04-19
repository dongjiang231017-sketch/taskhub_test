document.addEventListener('DOMContentLoaded', function () {
    const coinTable = document.getElementById('coin-table');
    if (coinTable) {
        try {
            const coins = JSON.parse(coinTable.dataset.coins || '[]');
            const tbody = coinTable.querySelector('tbody');
            const renderCoins = function () {
                tbody.innerHTML = coins.map((coin, index) => {
                    const sign = coin.change >= 0 ? '+' : '';
                    return `<tr><td>${index + 1}</td><td>${coin.symbol} ${coin.name}</td><td>${coin.price.toFixed(2)}</td><td class="${coin.change >= 0 ? 'positive' : 'negative'}">${sign}${coin.change.toFixed(2)}%</td></tr>`;
                }).join('');
            };
            const updateCoins = function () {
                coins.forEach(function (coin) {
                    const delta = (Math.random() - 0.5) * 2;
                    coin.price = Math.max(0.01, coin.price + delta);
                    coin.change = parseFloat((Math.random() * 2 - 1).toFixed(2));
                });
                renderCoins();
            };
            renderCoins();
            setInterval(updateCoins, 3000);
        } catch (error) {
            console.error('无法解析币种列表', error);
        }
    }

    const carouselItems = document.querySelectorAll('.carousel-item');
    if (carouselItems.length > 1) {
        let currentIndex = 0;
        setInterval(function () {
            carouselItems[currentIndex].classList.remove('active');
            currentIndex = (currentIndex + 1) % carouselItems.length;
            carouselItems[currentIndex].classList.add('active');
        }, 5000);
    }
});
