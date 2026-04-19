(function () {
    function init() {
        if (typeof flatpickr === 'undefined') {
            return;
        }
        var zh =
            typeof flatpickr.l10ns !== 'undefined' && flatpickr.l10ns.zh
                ? flatpickr.l10ns.zh
                : null;
        document.querySelectorAll('input.announcements-dtp').forEach(function (el) {
            if (el._flatpickr) {
                return;
            }
            var opts = {
                enableTime: true,
                time_24hr: true,
                allowInput: true,
                clickOpens: true,
                dateFormat: 'Y-m-d H:i',
                minuteIncrement: 1,
            };
            if (zh) {
                opts.locale = zh;
            }
            flatpickr(el, opts);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
