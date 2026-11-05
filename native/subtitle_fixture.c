/* MIT License. Generate authored bitmap fixtures through FFmpeg's public API. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/mem.h>

static void check(int result, const char *operation) {
    if (result < 0) {
        char error[256];
        av_strerror(result, error, sizeof(error));
        fprintf(stderr, "%s: %s\n", operation, error);
        exit(1);
    }
}

static void write_subtitle(AVFormatContext *format, AVStream *stream, AVCodecContext *codec,
                           AVSubtitle *subtitle, int64_t pts, int duration) {
    const int capacity = 1024 * 1024;
    uint8_t *buffer = av_malloc(capacity);
    int count = avcodec_encode_subtitle(codec, buffer, capacity, subtitle);
    check(count, "encode");
    if (count) {
        AVPacket *packet = av_packet_alloc();
        check(av_new_packet(packet, count), "packet");
        memcpy(packet->data, buffer, count);
        packet->pts = packet->dts = pts;
        packet->duration = duration;
        packet->stream_index = stream->index;
        av_packet_rescale_ts(packet, (AVRational){1, 1000}, stream->time_base);
        check(av_interleaved_write_frame(format, packet), "write");
        av_packet_free(&packet);
    }
    av_free(buffer);
}

int main(int argc, char **argv) {
    if (argc != 4) return 2;
    const AVCodec *encoder = avcodec_find_encoder_by_name(argv[1]);
    if (!encoder) return 3;
    AVFormatContext *format = NULL;
    check(avformat_alloc_output_context2(&format, NULL, argv[2], argv[3]), "format");
    format->max_delay = 0;
    AVCodecContext *codec = avcodec_alloc_context3(encoder);
    codec->width = 720;
    codec->height = 576;
    codec->time_base = (AVRational){1, 1000};
    if (format->oformat->flags & AVFMT_GLOBALHEADER) codec->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
    check(avcodec_open2(codec, encoder, NULL), "open encoder");
    AVStream *stream = avformat_new_stream(format, NULL);
    stream->time_base = (AVRational){1, 1000};
    check(avcodec_parameters_from_context(stream->codecpar, codec), "parameters");
    check(avio_open(&format->pb, argv[3], AVIO_FLAG_WRITE), "open output");
    check(avformat_write_header(format, NULL), "header");
    AVSubtitle subtitle = {0};
    subtitle.pts = 1000000;
    subtitle.end_display_time = 3000;
    subtitle.num_rects = 1;
    subtitle.rects = av_mallocz(sizeof(*subtitle.rects));
    AVSubtitleRect *rect = av_mallocz(sizeof(*rect));
    subtitle.rects[0] = rect;
    rect->type = SUBTITLE_BITMAP;
    rect->x = 100;
    rect->y = 100;
    rect->w = 120;
    rect->h = 30;
    rect->nb_colors = 4;
    rect->linesize[0] = rect->w;
    rect->data[0] = av_malloc(rect->w * rect->h);
    memset(rect->data[0], 1, rect->w * rect->h);
    rect->data[1] = av_mallocz(4 * sizeof(uint32_t));
    ((uint32_t *)rect->data[1])[1] = 0xffffffff;
    write_subtitle(format, stream, codec, &subtitle, 1000, 3000);
    if (!strcmp(argv[1], "dvbsub")) {
        AVSubtitle clear = {0};
        clear.pts = 4000000;
        write_subtitle(format, stream, codec, &clear, 4000, 0);
    }
    check(av_write_trailer(format), "trailer");
    avsubtitle_free(&subtitle);
    avcodec_free_context(&codec);
    avio_closep(&format->pb);
    avformat_free_context(format);
    return 0;
}
