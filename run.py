import multiprocessing

if __name__ == '__main__':
    # PyInstaller must intercept worker/resource-tracker subprocess arguments
    # before argparse or Qt initialization, especially for speech model downloads.
    multiprocessing.freeze_support()
    from llplayer.app import main
    main()
