% Exercise the standalone runtime, GIFT NIfTI IO, numerics, and plotting.
% Run through run_groupica.sh with /checks bound to a writable scratch directory.
try
    rng(0, 'twister');
    X = [ones(24, 1), (1:24)', sin((1:24)')];
    Y = reshape(sin(1:120), 24, 5);
    beta = X \ Y;
    spectrum = abs(fft(Y));
    covariance = cov(Y);
    probabilities = erf([-3, -1, 0, 1, 3] / sqrt(2));
    V = icatb_spm_vol('/workspace/app/local_data/mask.nii');
    mask = icatb_spm_read_vols(V);
    mask_summary = [size(mask), sum(mask(:)), nnz(mask)];
    save('/checks/numerics.mat', 'beta', 'spectrum', 'covariance', ...
        'probabilities', 'mask_summary', '-v7');
    f = figure('Visible', 'off');
    plot(Y(:, 1));
    title('Mancova runtime smoke');
    print(f, '/checks/plot.png', '-dpng');
    close(f);
    fid = fopen('/checks/success.txt', 'w');
    fprintf(fid, 'runtime smoke passed\n');
    fclose(fid);
    exit(0);
catch err
    disp(getReport(err, 'extended'));
    exit(1);
end
